#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os

from kubernetes import client

from kserve import KServeClient
from kserve import constants
from kserve import V1beta1PredictorSpec
from kserve import V1beta1InferenceServiceSpec
from kserve import V1beta1ExplainerSpec
from kserve import V1beta1AIXExplainerSpec
from kserve import V1beta1InferenceService
from kubernetes.client import V1ResourceRequirements
from kubernetes.client import V1Container

from ..common.utils import predict
from ..common.utils import explain_aix
from ..common.utils import KSERVE_TEST_NAMESPACE

import numpy as np

logging.basicConfig(level=logging.INFO)
kserve_client = KServeClient(config_file=os.environ.get("KUBECONFIG", "~/.kube/config"))


def test_tabular_explainer():
    service_name = 'aix-explainer'
    predictor = V1beta1PredictorSpec(
        containers=[V1Container(
                    name="predictor",
                    image='aipipeline/rf-predictor:0.4.0',
                    command=["python", "-m", "rfserver", "--model_name", "aix-explainer"],
                    resources=V1ResourceRequirements(
                        requests={'cpu': '10m', 'memory': '128Mi'},
                        limits={'cpu': '100m', 'memory': '256Mi'}
                    ))]
    )
    explainer = V1beta1ExplainerSpec(
        min_replicas=1,
        aix=V1beta1AIXExplainerSpec(
            name='explainer',
            type='LimeImages',
            resources=V1ResourceRequirements(
                requests={'cpu': '10m', 'memory': '128Mi'},
                limits={'cpu': '100m', 'memory': '256Mi'}
            )
        )
    )

    isvc = V1beta1InferenceService(api_version=constants.KSERVE_V1BETA1,
                                   kind=constants.KSERVE_KIND,
                                   metadata=client.V1ObjectMeta(
                                       name=service_name, namespace=KSERVE_TEST_NAMESPACE),
                                   spec=V1beta1InferenceServiceSpec(predictor=predictor, explainer=explainer))

    kserve_client.create(isvc)
    try:
        kserve_client.wait_isvc_ready(service_name, namespace=KSERVE_TEST_NAMESPACE, timeout_seconds=720)
    except RuntimeError as e:
        logging.info(kserve_client.api_instance.get_namespaced_custom_object("serving.knative.dev", "v1",
                     KSERVE_TEST_NAMESPACE, "services", service_name + "-predictor-default"))
        pods = kserve_client.core_api.list_namespaced_pod(KSERVE_TEST_NAMESPACE,
                                                          label_selector='serving.kserve.io/inferenceservice={}'
                                                          .format(service_name))
        for pod in pods.items:
            logging.info(pod)
        raise e

    res = predict(service_name, './data/mnist_input.json')
    assert(res["predictions"] == [[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]])

    mask = explain_aix(service_name, './data/mnist_input.json')
    percent_in_mask = np.count_nonzero(mask) / np.size(np.array(mask))
    assert(percent_in_mask > 0.6)
    kserve_client.delete(service_name, KSERVE_TEST_NAMESPACE)
