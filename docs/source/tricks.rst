Tricks
======

.. _tricks:

.. note::

    Time series forecasting is a classic example of the "No Free Lunch" scenario. Deep learning models, in particular, require careful tuning of architecture, hyper-parameters, and preprocessing strategies to achieve meaningful results on time series tasks.


Use tfts in competition flexible
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want a better performance, you can import tfts source code to modify it directly. That's how I use it in competitions.

* `The TFTS BERT model <https://github.com/LongxingTan/KDDCup2022-Baidu>`_ wins the 3rd place in `Baidu KDD Cup 2022 <https://aistudio.baidu.com/aistudio/competition/detail/152/0/introduction>`_
* `The TFTS Seq2Seq mode <https://github.com/LongxingTan/Data-competitions/tree/master/tianchi-enso-prediction>`_ wins the 4th place of `Tianchi ENSO prediction <https://tianchi.aliyun.com/competition/entrance/531871/introduction>`_


General Tricks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There is no free launch, and it's impossible to forecast the future. So we should understand first how to forecast based on the trend, seasonality, cyclicity and noise.

* target transformation

	skip connect. skip connect from ResNet is a special and common target transformation, tfts provides some basic skip connect in model config. If you want try more skip connect, please use ``AutoModel`` to make custom model.

* feature engineering

    feature engineering is a art.

* different temporal scale

	we can train different models from different scale

* module usage

    Be careful to use the layer like `Dropout` or `BatchNorm` for regression task


* Multi-steps prediction strategy

    * multi models for single variable prediction
    * add a hidden-sizes dense layer at last
    * encoder-decoder structure
    * encoder-forecasting structure


.. code-block:: python

    # use tfts auto-regressive generate multiple steps
    from tfts.data import TimeSeriesSequence
    # Generate predictions
    last_sequence = data.tail(10)

    # Function to add features after each prediction
    def add_features(new_df, history_df):
        # Add any features needed for the next prediction
        # For example, you could add lag features, moving averages, etc.
        return new_df

    # Generate predictions
    predictions = model.generate(
        last_sequence,
        generation_config={
            'steps': 30,
            'time_idx': 'time_idx',
            'time_step': 1,
            'add_features_func': add_features
        }
    )
