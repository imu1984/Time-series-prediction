"""
`WaveNet: A Generative Model for Raw Audio
<https://arxiv.org/abs/1609.03499>`_
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import tensorflow as tf
from tensorflow.keras.layers import Concatenate, Dense, Lambda, ReLU

from tfts.layers.cnn_layer import ConvTemp
from tfts.layers.dense_layer import DenseTemp

from .base import BaseConfig, BaseModel

logger = logging.getLogger(__name__)


class WaveNetConfig(BaseConfig):
    model_type: str = "wavenet"

    def __init__(
        self,
        dilation_rates: List[int] = None,
        kernel_sizes: List[int] = None,
        filters: int = 128,
        dense_hidden_size: int = 64,
        scheduled_sampling: float = 1.0,
        use_attention: bool = False,
        attention_size: int = 64,
        num_attention_heads: int = 2,
        attention_probs_dropout_prob: float = 0.0,
        **kwargs,
    ) -> None:
        """
        Initializes the configuration for the WaveNet model with the specified parameters.

        Args:
            dilation_rates: List of dilation rates for the convolutional layers.
            kernel_sizes: List of kernel sizes for the convolutional layers.
            filters: The number of filters in the convolutional layers.
            dense_hidden_size: The size of the dense hidden layer following the convolutional layers.
            scheduled_sampling: Scheduled sampling ratio. 0 means teacher forcing, 1 means use last prediction
            use_attention: Whether to use attention mechanism in the model.
            attention_size: The size of the attention mechanism.
            num_attention_heads: The number of attention heads.
            attention_probs_dropout_prob: Dropout probability for attention probabilities.
        """
        super(WaveNetConfig, self).__init__()

        self.dilation_rates: List[int] = dilation_rates or [2**i for i in range(4)]
        self.kernel_sizes: List[int] = kernel_sizes or [2] * 4
        self.filters: int = filters
        self.dense_hidden_size: int = dense_hidden_size
        self.scheduled_sampling: float = scheduled_sampling
        self.use_attention: bool = use_attention
        self.attention_size: int = attention_size
        self.num_attention_heads: int = num_attention_heads
        self.attention_probs_dropout_prob: float = attention_probs_dropout_prob


class WaveNet(BaseModel):
    """WaveNet model for time series"""

    def __init__(self, predict_sequence_length: int = 1, config: Optional[WaveNetConfig] = None) -> None:
        """
        Initializes the WaveNet model.

        Args:
            predict_sequence_length: Length of the prediction sequence.
            config: Configuration object containing model parameters.
        """
        super(WaveNet, self).__init__()
        self.config = config or WaveNetConfig()
        self.predict_sequence_length = predict_sequence_length
        self.encoder = Encoder(
            kernel_sizes=self.config.kernel_sizes,
            dilation_rates=self.config.dilation_rates,
            filters=self.config.filters,
            dense_hidden_size=self.config.dense_hidden_size,
        )
        self.decoder = DecoderV1(
            filters=self.config.filters,
            dilation_rates=self.config.dilation_rates,
            dense_hidden_size=self.config.dense_hidden_size,
            predict_sequence_length=self.predict_sequence_length,
        )

    def __call__(
        self,
        inputs: tf.Tensor,
        teacher: Optional[tf.Tensor] = None,
        output_hidden_states: Optional[bool] = None,
        return_dict: Optional[bool] = None,
    ):
        """
        Forward pass for the WaveNet model.

        Args:
            inputs: Input tensor for the model.
            teacher: Teacher tensor used for scheduled sampling.
            output_hidden_states: Flag to output the hidden statues
            return_dict: Flag to control the return type.

        Returns:
            Tensor containing the model output.
        """
        x, encoder_feature, decoder_feature = self._prepare_3d_inputs(inputs, ignore_decoder_inputs=False)
        encoder_state, encoder_outputs = self.encoder(encoder_feature)
        decoder_outputs = self.decoder(
            decoder_features=decoder_feature,
            # imagine the first dim is the predict
            decoder_init_input=x[:, -1, 0:1],
            teacher=teacher,
            encoder_outputs=encoder_outputs,
        )
        return decoder_outputs


class Encoder(tf.keras.layers.Layer):
    """Encoder block for the WaveNet model."""

    def __init__(
        self, kernel_sizes: List[int], filters: int, dilation_rates: List[int], dense_hidden_size: int, **kwargs
    ) -> None:
        """
        Initializes the encoder block.

        Args:
            kernel_sizes: List of kernel sizes for convolutional layers.
            filters: Number of filters for convolutional layers.
            dilation_rates: Dilation rates for the convolutions.
            dense_hidden_size: Hidden size for the dense layers.
        """
        super(Encoder, self).__init__(**kwargs)
        self.filters = filters
        self.conv_times = []
        for i, (kernel_size, dilation) in enumerate(zip(kernel_sizes, dilation_rates)):
            self.conv_times.append(
                ConvTemp(filters=2 * filters, kernel_size=kernel_size, causal=True, dilation_rate=dilation)
            )
        self.dense_time1 = DenseTemp(hidden_size=filters, activation="tanh", name="encoder_dense_time1")
        self.dense_time2 = DenseTemp(hidden_size=filters + filters, name="encoder_dense_time2")
        self.dense_time3 = DenseTemp(hidden_size=dense_hidden_size, activation="relu", name="encoder_dense_time3")
        self.dense_time4 = DenseTemp(hidden_size=1, name="encoder_dense_time_4")

    def call(self, x: tf.Tensor):
        inputs = self.dense_time1(inputs=x)

        skip_outputs = []
        conv_inputs = [inputs]
        for conv_time in self.conv_times:
            dilated_conv = conv_time(inputs)
            split_layer = Lambda(lambda x: tf.split(x, 2, axis=2))
            conv_filter, conv_gate = split_layer(dilated_conv)
            dilated_conv = Lambda(lambda x: tf.nn.tanh(x[0]) * tf.nn.sigmoid(x[1]))([conv_filter, conv_gate])
            outputs = self.dense_time2(inputs=dilated_conv)
            split_layer2 = Lambda(lambda x: tf.split(x, [self.filters, self.filters], axis=2))
            skips, residuals = split_layer2(outputs)
            inputs += residuals
            conv_inputs.append(inputs)  # batch_size * time_sequence_length * filters
            skip_outputs.append(skips)

        concat_layer = Concatenate(axis=2)
        concatenated = concat_layer(skip_outputs)
        relu_layer = ReLU()
        skip_outputs = relu_layer(concatenated)
        # skip_outputs = tf.nn.relu(tf.concat(skip_outputs, axis=2))
        h = self.dense_time3(skip_outputs)
        # [batch_size, time_sequence_length, filters] * time_sequence_length
        y_hat = self.dense_time4(h)
        return y_hat, conv_inputs[:-1]


class DecoderV1(tf.keras.layers.Layer):
    """Decoder block for WaveNet V1."""

    def __init__(
        self,
        filters: int,
        dilation_rates: List[int],
        dense_hidden_size: int,
        predict_sequence_length: int = 24,
        **kwargs,
    ) -> None:
        """
        Initializes the decoder block.

        Args:
            filters: Number of filters for convolutional layers.
            dilation_rates: Dilation rates for convolutions.
            dense_hidden_size: Size of the dense hidden layer.
            predict_sequence_length: Length of the predicted sequence.
        """
        super().__init__(**kwargs)
        self.filters: int = filters
        self.predict_sequence_length = predict_sequence_length
        self.dilation_rates = dilation_rates
        self.dense_hidden_size = dense_hidden_size

    def build(self, input_shape, **kwargs):
        batch_size = input_shape[0]
        decoder_input_size = input_shape[-1] + 1

        self.dense1 = Dense(self.filters, activation="tanh")
        self.dense1.build([batch_size, decoder_input_size])

        self.dense2 = Dense(2 * self.filters, use_bias=True)
        self.dense2.build([batch_size, self.filters])

        self.dense3 = Dense(2 * self.filters, use_bias=False)
        self.dense3.build([batch_size, self.filters])

        self.dense4 = Dense(2 * self.filters)
        self.dense4.build([batch_size, self.filters])

        total_skips = self.filters * len(self.dilation_rates)
        self.dense5 = Dense(self.dense_hidden_size, activation="relu")
        self.dense5.build([batch_size, total_skips])

        self.dense6 = Dense(1)
        self.dense6.build([batch_size, self.dense_hidden_size])

        super().build(input_shape)

    def call(
        self,
        decoder_features,
        decoder_init_input,
        encoder_outputs,
        teacher: Optional[tf.Tensor] = None,
        scheduled_sampling: float = 0.0,
        training: Optional[bool] = None,
        **kwargs: Dict,
    ):
        """
        Forward pass for the decoder block.

        Args:
            decoder_features: Tensor containing decoder features.
            decoder_init_input: Initial input for the decoder.
            encoder_outputs: List of encoder outputs.
            teacher: Optional tensor for teacher forcing.
            scheduled_sampling: Probability of using teacher forcing.
            training: Whether the model is in training mode.

        Returns:
            Decoder output tensor.
        """
        decoder_outputs = []
        prev_output = decoder_init_input  # the initial input for decoder

        for i in range(self.predict_sequence_length):
            if training:
                p = np.random.uniform(low=0, high=1, size=1)[0]
                if teacher is not None and p > scheduled_sampling:
                    this_input = teacher[:, i : i + 1]
                else:
                    this_input = prev_output
            else:
                this_input = prev_output

            if decoder_features is not None:
                # this_input = tf.concat([this_input, decoder_features[:, i]], axis=-1)
                this_input = Concatenate(axis=-1)([this_input, decoder_features[:, i]])

            x = self.dense1(this_input)
            skip_outputs = []

            for i, dilation in enumerate(self.dilation_rates):
                safe_dilation = min(dilation, encoder_outputs[i].shape[1])
                if dilation > encoder_outputs[i].shape[1]:
                    logger.warning(
                        f"Dilation {dilation} exceeds context length {encoder_outputs[i].shape[1]}. "
                        "Using {safe_dilation} instead."
                    )
                    dilation = safe_dilation

                state = encoder_outputs[i][:, -dilation, :]

                # use 2 dense layer to calculate a kernel=2 convolution
                dilated_conv = self.dense2(state) + self.dense3(x)
                # conv_filter, conv_gate = tf.split(dilated_conv, 2, axis=1)
                split_layer = Lambda(lambda x: tf.split(x, 2, axis=1))
                conv_filter, conv_gate = split_layer(dilated_conv)
                # dilated_conv = tf.nn.tanh(conv_filter) * tf.nn.sigmoid(conv_gate)
                dilated_conv = Lambda(lambda x: tf.nn.tanh(x[0]) * tf.nn.sigmoid(x[1]))([conv_filter, conv_gate])

                out = self.dense4(dilated_conv)
                # skip, residual = tf.split(out, 2, axis=1)
                split_layer = Lambda(lambda x: tf.split(x, [self.filters, self.filters], axis=1))
                skips, residuals = split_layer(out)
                x += residuals
                # encoder_outputs[i] = tf.concat([encoder_outputs[i], tf.expand_dims(x, 1)], axis=1)
                expand = Lambda(lambda t: tf.expand_dims(t, axis=1))
                encoder_outputs[i] = Concatenate(1)([encoder_outputs[i], expand(x)])
                skip_outputs.append(skips)

            # skip_outputs = tf.nn.relu(tf.concat(skip_outputs, axis=1))
            concatenated = Concatenate(axis=1)(skip_outputs)
            skip_outputs = ReLU()(concatenated)

            skip_outputs = self.dense5(skip_outputs)
            this_output = self.dense6(skip_outputs)
            decoder_outputs.append(this_output)

        # decoder_outputs = tf.concat(decoder_outputs, axis=1)
        decoder_outputs = Concatenate(1)(decoder_outputs)
        expand = Lambda(lambda t: tf.expand_dims(t, axis=-1))
        return expand(decoder_outputs)

    def get_config(self):
        config = super().get_config()
        config.update(
            {
                "filters": self.filters,
                "dilation_rates": self.dilation_rates,
                "dense_hidden_size": self.dense_hidden_size,
                "predict_sequence_length": self.predict_sequence_length,
            }
        )
        return config

    def compute_output_shape(self, input_shape):
        batch_size = input_shape[0]
        return (batch_size, self.predict_sequence_length, 1)


class DecoderV2(tf.keras.layers.Layer):
    """Decoder need avoid future data leaks"""

    def __init__(
        self,
        filters: int,
        dilation_rates: List[int],
        dense_hidden_size: int,
        predict_sequence_length: int = 24,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.filters = filters
        self.dilation_rates = dilation_rates
        self.predict_sequence_length = predict_sequence_length
        self.dense_hidden_size = dense_hidden_size

    def build(self, input_shape):
        super().build(input_shape)
        self.dense_1 = Dense(self.filters, activation="tanh", name="decoder_dense_1")
        self.dense_2 = Dense(2 * self.filters, name="decoder_dense_2")
        self.dense_3 = Dense(2 * self.filters, use_bias=False, name="decoder_dense_3")
        self.dense_4 = Dense(2 * self.filters, name="decoder_dense_4")
        self.dense_5 = Dense(self.dense_hidden_size, activation="relu", name="decoder_dense_5")
        self.dense_6 = Dense(1, name="decoder_dense_6")

    def call(
        self,
        decoder_features: tf.Tensor,
        decoder_init_input: tf.Tensor,
        encoder_states: tf.Tensor,
        teacher: Optional[tf.Tensor] = None,
    ):
        """
        Forward pass for the decoder block v2.

        Args:
            decoder_features: Tensor containing decoder features.
            decoder_init_input: Initial input for the decoder.
            encoder_states: List of encoder outputs.
            teacher: Optional tensor for teacher forcing.

        Returns:
            Decoder output tensor.
        """

        def cond_fn(time, prev_output, decoder_output_ta):
            return time < self.predict_sequence_length

        def body(time, prev_output, decoder_output_ta):
            if time == 0 or teacher is None:
                current_input = prev_output
            else:
                current_input = teacher[:, time - 1, :]

            if decoder_features is not None:
                current_feature = decoder_features[:, time, :]
                current_input = tf.concat([current_input, current_feature], axis=1)

            inputs = self.dense_1(current_input)

            skip_outputs = []
            for i, dilation in enumerate(self.dilation_rates):
                state = encoder_states[i][:, -dilation, :]

                dilated_conv = self.dense_2(state) + self.dense_3(inputs)
                conv_filter, conv_gate = tf.split(dilated_conv, 2, axis=1)
                dilated_conv = tf.nn.tanh(conv_filter) * tf.nn.sigmoid(conv_gate)
                outputs = self.dense_4(dilated_conv)
                skips, residuals = tf.split(outputs, [self.filters, self.filters], axis=1)
                inputs += residuals
                encoder_states[i] = tf.concat([encoder_states[i], tf.expand_dims(inputs, 1)], axis=1)
                skip_outputs.append(skips)

            skip_outputs = tf.nn.relu(tf.concat(skip_outputs, axis=1))
            h = self.dense_5(skip_outputs)
            y_hat = self.dense_6(h)
            decoder_output_ta = decoder_output_ta.write(time, y_hat)
            return time + 1, y_hat, decoder_output_ta

        loop_init = [
            tf.constant(0, dtype=tf.int32),
            decoder_init_input,
            tf.TensorArray(dtype=tf.float32, size=self.predict_sequence_length),
        ]
        _, _, decoder_outputs_ta = tf.while_loop(cond=cond_fn, body=body, loop_vars=loop_init)
        decoder_outputs = decoder_outputs_ta.stack()
        decoder_outputs = tf.transpose(decoder_outputs, [1, 0, 2])
        return decoder_outputs
