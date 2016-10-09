# Copyright 2015 Google Inc. All Rights Reserved.
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

"""Trains and Evaluates the MNIST network using a feed dictionary."""
# pylint: disable=missing-docstring
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os.path
import time

import numpy
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf

import input_data
import files_client_thread
import model_build 
import math
import numpy as np

from PIL import Image


# Basic model parameters as external flags.
flags = tf.app.flags
gpu_num = 4 
#flags.DEFINE_float('learning_rate', 0.0, 'Initial learning rate.')
flags.DEFINE_string("job_name", "", "Either 'ps' or 'worker'")
flags.DEFINE_integer("task_index", 0, "Index of task within the job")
flags.DEFINE_float('learning_rate', 1e-4, 'Initial learning rate.')
flags.DEFINE_integer('max_steps', 20000, 'Number of steps to run trainer.')
flags.DEFINE_integer('batch_size', 16 , 'Batch size.  '
                     'Must divide evenly into the dataset sizes.')
flags.DEFINE_string('train_dir', './', 'Directory to put the training data.')

FLAGS = flags.FLAGS



def placeholder_inputs(batch_size):
  """Generate placeholder variables to represent the input tensors.

  These placeholders are used as inputs by the rest of the model building
  code and will be fed from the downloaded data in the .run() loop, below.

  Args:
    batch_size: The batch size will be baked into both placeholders.

  Returns:
    images_placeholder: Images placeholder.
    labels_placeholder: Labels placeholder.
  """
  # Note that the shapes of the placeholders match the shapes of the full
  # image and label tensors, except the first dimension is now batch_size
  # rather than the full size of the train or test data sets.
  images_placeholder = tf.placeholder(tf.float32, shape=(batch_size,
                                                         16,
                                                         model_build.IMAGE_SIZE,
                                                         model_build.IMAGE_SIZE,
                                                         model_build.CHANNELS))
  #images_placeholder = tf.placeholder(tf.float32, shape=(batch_size,28,28,1))
  labels_placeholder = tf.placeholder(tf.int64, shape=(batch_size))
  return images_placeholder, labels_placeholder


def _variable_on_cpu(name, shape, initializer):
  #with tf.device('/cpu:%d' % cpu_id):
  with tf.device('/cpu:0'):
    var = tf.get_variable(name, shape, initializer=initializer)
  return var

def _variable_with_weight_decay(name, shape, stddev, wd):
  var = _variable_on_cpu(name, shape,tf.truncated_normal_initializer(stddev=stddev))
  if wd is not None:
    weight_decay = tf.mul(tf.nn.l2_loss(var), wd, name='weight_loss')
    tf.add_to_collection('losses', weight_decay)
  return var

def run_test():
  fc = files_client_thread.FileClient("10.58.116.230", 4170,FLAGS.batch_size*gpu_num, 16)
  # Get the sets of images and labels for training, validation, and
  images_placeholder, labels_placeholder = placeholder_inputs(FLAGS.batch_size*gpu_num)
  with tf.variable_scope('c3d_var') as var_scope:
    weights = {
            'wc1': _variable_with_weight_decay('wc1',[3, 3, 3, 3, 64],0.04,0.00),
            'wc2': _variable_with_weight_decay('wc2',[3, 3, 3, 64, 128],0.04,0.00),
            'wc3a': _variable_with_weight_decay('wc3a',[3, 3, 3, 128, 256],0.04,0.00),
            'wc3b': _variable_with_weight_decay('wc3b',[3, 3, 3, 256, 256],0.04,0.00),
            'wc4a': _variable_with_weight_decay('wc4a',[3, 3, 3, 256, 512],0.04,0.00),
            'wc4b': _variable_with_weight_decay('wc4b',[3, 3, 3, 512, 512],0.04,0.00),
            'wc5a': _variable_with_weight_decay('wc5a',[2, 3, 3, 512, 512],0.04,0.00),
            'wc5b': _variable_with_weight_decay('wc5b',[1, 3, 3, 512, 512],0.04,0.00),
            'wd1': _variable_with_weight_decay('wd1',[8192, 4096],0.04,0.001),
            'wd2': _variable_with_weight_decay('wd2',[4096, 4096],0.04,0.002),
            'out': _variable_with_weight_decay('wout',[4096, model_build.NUM_CLASSES],0.04,0.005)
            }
    biases = {
            'bc1': _variable_with_weight_decay('bc1',[64],0.04,0.0),
            'bc2': _variable_with_weight_decay('bc2',[128],0.04,0.0),
            'bc3a': _variable_with_weight_decay('bc3a',[256],0.04,0.0),
            'bc3b': _variable_with_weight_decay('bc3b',[256],0.04,0.0),
            'bc4a': _variable_with_weight_decay('bc4a',[512],0.04,0.0),
            'bc4b': _variable_with_weight_decay('bc4b',[512],0.04,0.0),
            'bc5a': _variable_with_weight_decay('bc5a',[512],0.04,0.0),
            'bc5b': _variable_with_weight_decay('bc5b',[512],0.04,0.0),
            'bd1': _variable_with_weight_decay('bd1',[4096],0.04,0.0),
            'bd2': _variable_with_weight_decay('bd2',[4096],0.04,0.0),
            'out': _variable_with_weight_decay('bout',[model_build.NUM_CLASSES],0.04,0.0),
            }
  logits = []
  for gpu_index in range(0,gpu_num):
    with tf.device('/gpu:%d' % gpu_index):
      logit = model_build.inference_c3d(images_placeholder[gpu_index*FLAGS.batch_size:(gpu_index+1)*FLAGS.batch_size,:,:,:,:],0.6,FLAGS.batch_size,weights,biases) 
      logits.append(logit)
  logits = tf.concat(0,logits)
  norm_score = tf.nn.softmax(logits)
  saver = tf.train.Saver()
  sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True, log_device_placement=True))
  init = tf.initialize_all_variables()
  sess.run(init)
  # Create a saver for writing training checkpoints.
  saver.restore(sess,"model_c3d_0711")
  #sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True, log_device_placement=True))
  # Run the Op to initialize the variables.
  #init = tf.initialize_all_variables()
  #sess.run(init)
  # And then after everything is built, start the training loop.
  write_file = open("predict_ret.txt","w+")
  start_pos = 0
  all_steps = (int)(10000/(FLAGS.batch_size*gpu_num))
  for step in xrange(all_steps):
    # Fill a feed dictionary with the actual set of images and labels
    # for this particular training step.
    start_time = time.time()
    #test_images,train_labels,next_start_pos,predict_files = input_data.ReadTestDataLabelFromFile('bruce_list/test_pos.list',FLAGS.batch_size*gpu_num,start_pos)
    test_images,test_labels = input_data.ReadDataLabelFromServer(fc)
    predict_score = norm_score.eval(session = sess,feed_dict={images_placeholder: test_images}) 
    for i in range(0,FLAGS.batch_size*gpu_num):
      write_file.write(str(test_labels[i]))
      write_file.write(' ')
      write_file.write(str(predict_score[i][0]))
      write_file.write(' ')
      write_file.write(str(predict_score[i][1]))
      write_file.write('\n')
      write_file.flush()
  write_file.close()
  print("done")

def main(_):
  run_test()

if __name__ == '__main__':
  tf.app.run()
