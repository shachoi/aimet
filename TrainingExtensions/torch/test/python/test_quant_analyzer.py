# /usr/bin/env python3.5
# -*- mode: python -*-
# =============================================================================
#  @@-COPYRIGHT-START-@@
#
#  Copyright (c) 2022, Qualcomm Innovation Center, Inc. All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  1. Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
#  3. Neither the name of the copyright holder nor the names of its contributors
#     may be used to endorse or promote products derived from this software
#     without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
#  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
#  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
#  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
#  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
#  POSSIBILITY OF SUCH DAMAGE.
#
#  SPDX-License-Identifier: BSD-3-Clause
#
#  @@-COPYRIGHT-END-@@
# =============================================================================

import json
import os.path
import shutil
import torch

from aimet_torch.examples.test_models import TinyModel
from aimet_torch.tensor_quantizer import TensorQuantizer
from aimet_torch.qc_quantize_op import QcQuantizeWrapper
from aimet_torch.quantsim import QuantizationSimModel
from aimet_torch.quant_analyzer import QuantAnalyzer, CallbackFunc


def calibrate(model: torch.nn.Module, dummy_input: torch.Tensor):
    """
    Helper function to calibrate model given dummy input
    :param model: PyTorch model.
    :param dummy_input: dummy input to model.
    """
    model.eval()
    with torch.no_grad():
        model(dummy_input)

def evaluate(model: torch.nn.Module, dummy_input: torch.Tensor):
    """
    Helper function to evaluate model performance given dummy input
    :param model: PyTorch model
    :param dummy_input: dummy input to model.
    """
    model.eval()
    with torch.no_grad():
        model(dummy_input)
    return 0.8


class TestQuantAnalyzer:


    def test_check_model_sensitivity_to_quantization(self):
        """ test analyze_model_sensitivity API """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        fp32_acc, weight_quantized_acc, act_quantized_acc = quant_analyzer.check_model_sensitivity_to_quantization()

        assert fp32_acc >= weight_quantized_acc
        assert fp32_acc >= act_quantized_acc
        assert quant_analyzer._model is model

    def test_sort_quant_wrappers_based_on_occurrence(self):
        """ test sort quant wrappers based on occurrence """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        sim = QuantizationSimModel(model, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, CallbackFunc(None), CallbackFunc(None))
        sorted_quant_wrappers_dict = quant_analyzer._sort_quant_wrappers_based_on_occurrence(sim)
        assert isinstance(sorted_quant_wrappers_dict, dict)
        for quant_wrapper in sorted_quant_wrappers_dict.values():
            assert isinstance(quant_wrapper, QcQuantizeWrapper)
        assert len(sorted_quant_wrappers_dict) == 12

        # Verify the index of sorted quant wrappers.
        layer_names = list(sorted_quant_wrappers_dict.keys())
        assert layer_names.index("conv1") < layer_names.index("bn1")
        assert layer_names.index("conv4") < layer_names.index("fc")

    def test_get_enabled_quantizers(self):
        """ test sort quant wrappers based on occurrence """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        sim = QuantizationSimModel(model, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, CallbackFunc(None), CallbackFunc(None))
        sorted_quant_wrappers_dict = quant_analyzer._sort_quant_wrappers_based_on_occurrence(sim)
        enabled_quant_wrappers = quant_analyzer._get_enabled_quantizers(sorted_quant_wrappers_dict)

        for quant_wrapper, enabled_quantizers in enabled_quant_wrappers.items():
            assert isinstance(quant_wrapper, QcQuantizeWrapper)
            assert all(isinstance(quantizer, TensorQuantizer) for quantizer in enabled_quantizers)

        # Disable all the quantizers and verify enabled_quant_wrappers dictionary should be empty.
        for quant_wrapper in sim.quant_wrappers():
            quant_wrapper.enable_activation_quantizers(enabled=False)
            quant_wrapper.enable_param_quantizers(enabled=False)

        enabled_quant_wrappers = quant_analyzer._get_enabled_quantizers(sorted_quant_wrappers_dict)
        assert not enabled_quant_wrappers

    def test_perform_per_layer_analysis_by_enabling_quant_wrappers(self):
        """ test perform per layer analysis by enabling quant wrappers """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        module_names = []
        for name, _ in model.named_modules():
            module_names.append(name)

        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            layer_wise_eval_score_dict = quant_analyzer.perform_per_layer_analysis_by_enabling_quant_wrappers()
            print(layer_wise_eval_score_dict)
            assert type(layer_wise_eval_score_dict) == dict
            assert len(layer_wise_eval_score_dict) == 12

            # test whether layer_wise_eval_score_dict consists of correct keys (module names).
            for quant_wrapper_name in layer_wise_eval_score_dict.keys():
                assert quant_wrapper_name in module_names

                # Check if it is exported to correct html file.
                assert os.path.isfile("./tmp/per_layer_quant_enabled.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")

    def test_perform_per_layer_analysis_by_disabling_quant_wrappers(self):
        """ test perform per layer analysis by disabling quant wrappers """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        module_names = []
        for name, _ in model.named_modules():
            module_names.append(name)

        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            layer_wise_eval_score_dict = quant_analyzer.perform_per_layer_analysis_by_disabling_quant_wrappers()
            print(layer_wise_eval_score_dict)
            assert type(layer_wise_eval_score_dict) == dict
            assert len(layer_wise_eval_score_dict) == 12

            # test whether layer_wise_eval_score_dict consists of correct keys (module names).
            for quant_wrapper_name in layer_wise_eval_score_dict.keys():
                assert quant_wrapper_name in module_names

            # Check if it is exported to correct html file.
            assert os.path.isfile("./tmp/per_layer_quant_disabled.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")

    def test_export_per_layer_stats_histogram(self):
        """ test export_per_layer_stats_histogram() """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            quant_analyzer.export_per_layer_stats_histogram()

            # Check if it is exported to correct html file.
            assert os.path.exists("./tmp/activations_pdf")
            assert os.path.exists("./tmp/weights_pdf")
            assert os.path.isfile("./tmp/activations_pdf/conv1_input_0.html")
            assert os.path.isfile("./tmp/activations_pdf/conv1_output_0.html")
            assert os.path.isfile("./tmp/weights_pdf/conv1/conv1_weight_0.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")

    def test_export_per_layer_stats_histogram_per_channel(self):
        """ test export_per_layer_stats_histogram() for per channel quantization """
        results_dir = os.path.abspath("./tmp/")
        os.makedirs(results_dir, exist_ok=True)

        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        quantsim_config = {
            "defaults": {
                "ops": {
                    "is_output_quantized": "True"
                },
                "params": {
                    "is_quantized": "True"
                },
                "per_channel_quantization": "True",
            },
            "params": {},
            "op_type": {},
            "supergroups": [],
            "model_input": {},
            "model_output": {}
        }
        with open("./tmp/quantsim_config.json", 'w') as f:
            json.dump(quantsim_config, f)

        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            quant_analyzer.export_per_layer_stats_histogram(config_file="./tmp/quantsim_config.json")
            assert os.path.exists("./tmp/activations_pdf")
            assert os.path.exists("./tmp/weights_pdf")
            assert os.path.isfile("./tmp/activations_pdf/conv1_output_0.html")
            assert os.path.isfile("./tmp/weights_pdf/conv1/conv1_weight_0.html")
            assert os.path.isfile("./tmp/weights_pdf/conv1/conv1_weight_31.html")
            assert os.path.isfile("./tmp/weights_pdf/conv2/conv2_weight_0.html")
            assert os.path.isfile("./tmp/weights_pdf/conv2/conv2_weight_15.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")

    def test_export_per_layer_encoding_min_max_range(self):
        """ test export_per_layer_encoding_min_max_range() """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            quant_analyzer.export_per_layer_encoding_min_max_range()
            assert os.path.isfile("./tmp/min_max_range_all_weights.html")
            assert os.path.isfile("./tmp/min_max_range_all_activations.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")

    def test_analyze(self):
        """ test end to end for analyze() method """
        input_shape = (1, 3, 32, 32)
        dummy_input = torch.randn(*input_shape)
        model = TinyModel().eval()
        forward_pass_callback = CallbackFunc(calibrate, dummy_input)
        eval_callback = CallbackFunc(evaluate, dummy_input)
        quant_analyzer = QuantAnalyzer(model, dummy_input, forward_pass_callback, eval_callback)
        try:
            quant_analyzer.analyze()
            assert os.path.isfile("./tmp/per_layer_quant_disabled.html")
            assert os.path.isfile("./tmp/per_layer_quant_enabled.html")
            assert os.path.exists("./tmp/activations_pdf")
            assert os.path.exists("./tmp/weights_pdf")
            assert os.path.isfile("./tmp/min_max_range_all_weights.html")
            assert os.path.isfile("./tmp/min_max_range_all_activations.html")
        finally:
            if os.path.isdir("./tmp/"):
                shutil.rmtree("./tmp/")
