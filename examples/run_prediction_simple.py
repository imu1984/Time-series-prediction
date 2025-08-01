"""Demo of time series prediction by tfts
python run_prediction_simple.py --use_model rnn
"""

import argparse
import os
import random

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from tensorflow.keras.optimizers.schedules import LearningRateSchedule

import tfts
from tfts import AutoConfig, AutoModel, KerasTrainer


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=315, required=False, help="seed")
    parser.add_argument("--use_model", type=str, default="bert", help="model for train")
    parser.add_argument("--use_data", type=str, default="sine", help="dataset: sine or air passengers")
    parser.add_argument("--train_length", type=int, default=24, help="sequence length for train")
    parser.add_argument("--predict_sequence_length", type=int, default=12, help="sequence length for predict")
    parser.add_argument("--epochs", type=int, default=100, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=16, help="Batch size for training")
    parser.add_argument("--learning_rate", type=float, default=5e-4, help="learning rate for training")

    return parser.parse_args()


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    tf.random.set_seed(seed)


def run_train(args):
    set_seed(args.seed)
    train, valid = tfts.get_data(args.use_data, args.train_length, args.predict_sequence_length, test_size=0.2)
    optimizer = tf.keras.optimizers.Adam(args.learning_rate)
    loss_fn = tf.keras.losses.MeanSquaredError()

    # for strong seasonality data like sine or air passengers, set up skip_connect_circle True
    config = AutoConfig.for_model(args.use_model)
    model = AutoModel.from_config(config, predict_sequence_length=args.predict_sequence_length)

    trainer = KerasTrainer(model)
    trainer.train(
        train,
        valid,
        optimizer=optimizer,
        loss_fn=loss_fn,
        epochs=args.epochs,
        callbacks=[EarlyStopping("val_loss", patience=5)],
    )

    pred = trainer.predict(valid[0])
    trainer.plot(history=valid[0], true=valid[1], pred=pred)


if __name__ == "__main__":
    args = parse_args()
    run_train(args)
    plt.show()
