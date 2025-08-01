"""Layer for :py:class:`~tfts.models.wavenet` :py:class:`~tfts.models.transformer`"""

from typing import Optional, Tuple

import tensorflow as tf
from tensorflow.keras import activations, constraints, initializers, regularizers
from tensorflow.keras.layers import Dense


class DenseTemp(tf.keras.layers.Layer):
    def __init__(
        self,
        hidden_size: int,
        activation: Optional[str] = None,
        kernel_initializer: str = "glorot_uniform",
        kernel_regularizer: Optional[str] = None,
        kernel_constraint: Optional[str] = None,
        use_bias: bool = True,
        bias_initializer="zeros",
        trainable: bool = True,
        name=None,
    ):
        super(DenseTemp, self).__init__(trainable=trainable, name=name)
        self.hidden_size = hidden_size
        self.use_bias = use_bias
        self.activation = activation
        self.kernel_initializer = kernel_initializer
        self.kernel_regularizer = kernel_regularizer
        self.kernel_constraint = kernel_constraint
        self.bias_initializer = bias_initializer

    def build(self, input_shape: Tuple[int]):
        inputs_units: int = int(input_shape[-1])  # input.get_shape().as_list()[-1]
        self.kernel = self.add_weight(
            name="kernel",
            shape=(inputs_units, self.hidden_size),
            initializer=initializers.get(self.kernel_initializer),
            regularizer=regularizers.get(self.kernel_regularizer),
            constraint=constraints.get(self.kernel_constraint),
            dtype=tf.float32,
            trainable=True,
        )
        if self.use_bias:
            self.bias = self.add_weight(
                name="bias",
                shape=(self.hidden_size,),
                initializer=self.bias_initializer,
                dtype=self.dtype,
                trainable=True,
            )
        self.activation = activations.get(self.activation)
        super(DenseTemp, self).build(input_shape)

    def call(self, inputs):
        """Computes the output of the layer.

        Args:
            inputs: Tensor of shape (batch_size, sequence_length, input_dim)

        Returns:
            output: Tensor of shape (batch_size, sequence_length, hidden_size)
        """
        output = tf.einsum("ijk,kl->ijl", inputs, self.kernel)

        if self.use_bias:
            output += self.bias

        if self.activation is not None:
            output = self.activation(output)
        return output

    def get_config(self):
        config = {
            "hidden_size": self.hidden_size,
        }
        base_config = super(DenseTemp, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def compute_output_shape(self, input_shape):
        return tf.TensorShape(input_shape[:-1] + (self.hidden_size,))


class FeedForwardNetwork(tf.keras.layers.Layer):
    def __init__(self, hidden_size: int, intermediate_size: int, hidden_dropout_prob: float = 0.0, **kwargs):
        super(FeedForwardNetwork, self).__init__(**kwargs)
        self.hidden_size = hidden_size
        self.intermediate_size = intermediate_size
        self.hidden_dropout_prob = hidden_dropout_prob

    def build(self, input_shape: Tuple[Optional[int], ...]):
        self.intermediate_dense_layer = Dense(self.intermediate_size, use_bias=True, activation="relu")
        self.output_dense_layer = Dense(self.hidden_size, use_bias=True)
        super(FeedForwardNetwork, self).build(input_shape)

    def call(self, x: tf.Tensor):
        """Feed Forward Network of Transformer

        Parameters
        ----------
        x : tf.Tensor
            FFN 3D inputs

        Returns
        -------
        tf.Tensor
            FFN 3D outputs
        """
        output = self.intermediate_dense_layer(x)
        output = self.output_dense_layer(output)
        return output

    def get_config(self):
        config = {
            "hidden_size": self.hidden_size,
            "intermediate_size": self.intermediate_size,
            "hidden_dropout_prob": self.hidden_dropout_prob,
        }
        base_config = super(FeedForwardNetwork, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))
