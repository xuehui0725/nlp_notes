# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Masked language model network."""
# pylint: disable=g-classes-have-attributes
from __future__ import absolute_import
from __future__ import division
# from __future__ import google_type_annotations
from __future__ import print_function

import tensorflow as tf

from official.modeling import tf_utils

# 最顶层进行 MaskedLM 任务的层
@tf.keras.utils.register_keras_serializable(package='Text')
class MaskedLM(tf.keras.layers.Layer):
    """Masked language model network head for BERT modeling.
  
    This network implements a masked language model based on the provided network.
    It assumes that the network being passed has a "get_embedding_table()" method.
  
    Arguments:
      embedding_table: The embedding table of the targets.
      activation: The activation, if any, for the dense layer.
      initializer: The intializer for the dense layer. Defaults to a Glorot
        uniform initializer.
      output: The output style for this network. Can be either 'logits' or
        'predictions'.
    """
    
    def __init__(self,
                 embedding_table,
                 activation=None,
                 initializer='glorot_uniform',
                 output='logits',
                 name='cls/predictions',
                 **kwargs):
        super(MaskedLM, self).__init__(name=name, **kwargs)
        self.embedding_table = embedding_table
        self.activation = activation
        self.initializer = tf.keras.initializers.get(initializer)
        
        if output not in ('predictions', 'logits'):
            raise ValueError(
                ('Unknown `output` value "%s". `output` can be either "logits" or '
                 '"predictions"') % output)
        self._output_type = output
    
    def build(self, input_shape):
        self._vocab_size, hidden_size = self.embedding_table.shape
        self.dense = tf.keras.layers.Dense(
            hidden_size,
            activation=self.activation,
            kernel_initializer=self.initializer,
            name='transform/dense')
        self.layer_norm = tf.keras.layers.LayerNormalization(
            axis=-1, epsilon=1e-12, name='transform/LayerNorm')
        self.bias = self.add_weight(
            'output_bias/bias',
            shape=(self._vocab_size,),
            initializer='zeros',
            trainable=True)
        
        super(MaskedLM, self).build(input_shape)
    
    def call(self, sequence_data, masked_positions):
        # 从输入中选择出 被遮蔽单词 对应的向量, batch*num_predictions,width
        masked_lm_input = self._gather_indexes(sequence_data, masked_positions)
        lm_data = self.dense(masked_lm_input)
        lm_data = self.layer_norm(lm_data)
        
        # 将被遮蔽的单词向量，与词表相乘，得到被遮蔽单词对应的概率分布 batch*num_predictions,vocab_size
        lm_data = tf.matmul(lm_data, self.embedding_table, transpose_b=True)
        # 加上偏置
        logits = tf.nn.bias_add(lm_data, self.bias)
        
        masked_positions_shape = tf_utils.get_shape_list(
            masked_positions, name='masked_positions_tensor')
        
        # 权重分布， batch，num_predictions,vocab_size
        logits = tf.reshape(logits,
                            [-1, masked_positions_shape[1], self._vocab_size])
        if self._output_type == 'logits':
            return logits
        return tf.nn.log_softmax(logits)
    
    def get_config(self):
        raise NotImplementedError('MaskedLM cannot be directly serialized because '
                                  'it has variable sharing logic.')
    
    def _gather_indexes(self, sequence_tensor, positions):
        """Gathers the vectors at the specific positions.
    
        Args:
            sequence_tensor: Sequence output of `BertModel` layer of shape
              (`batch_size`, `seq_length`, num_hidden) where num_hidden is number of
              hidden units of `BertModel` layer.
            positions: Positions ids of tokens in sequence to mask for pretraining
              of with dimension (batch_size, num_predictions) where
              `num_predictions` is maximum number of tokens to mask out and predict
              per each sequence.
    
        Returns:
            Masked out sequence tensor of shape (batch_size * num_predictions,
            num_hidden).
        """
        sequence_shape = tf_utils.get_shape_list(
            sequence_tensor, name='sequence_output_tensor')
        batch_size, seq_length, width = sequence_shape
        
        # positions 为遮蔽的单词的 id， 形状 batch,num_predictions
        # 获取被遮蔽单词，在批量序列展平后，对应的索引
        flat_offsets = tf.reshape(
            tf.range(0, batch_size, dtype=tf.int32) * seq_length, [-1, 1])
        flat_positions = tf.reshape(positions + flat_offsets, [-1])
        
        # 将输入展平，
        flat_sequence_tensor = tf.reshape(sequence_tensor,
                                          [batch_size * seq_length, width])
        output_tensor = tf.gather(flat_sequence_tensor, flat_positions)
        
        # 获取被遮蔽单词 batch*num_predictions, width
        return output_tensor