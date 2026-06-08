#include <graph/Graph.h>
#include <model/Model.h>
#include <neat.h>
#include <pipeline/Graph.h>
#include <pipeline/GraphOptions.h>
#include <pipeline/TensorCore.h>
#include <pipeline/TensorSpec.h>
#include <policy/DefaultPolicy.h>

#include <cstdint>
#include <iostream>
#include <vector>

int main() {
  auto storage = simaai::neat::make_cpu_owned_storage(64);
  if (!storage) {
    std::cerr << "failed to allocate representative tensor storage\n";
    return 1;
  }

  simaai::neat::Tensor tensor;
  tensor.dtype = simaai::neat::TensorDType::UInt8;
  tensor.shape = {1, 8, 8, 1};
  tensor.strides_bytes = {64, 8, 1, 1};
  tensor.storage = storage;
  tensor.device = {.type = simaai::neat::DeviceType::CPU, .id = 0};

  simaai::neat::TensorConstraint constraint;
  constraint.dtypes = {simaai::neat::TensorDType::UInt8};
  constraint.rank = 4;
  constraint.shape = {1, 8, 8, 1};
  constraint.device = tensor.device;

  if (!constraint.matches(tensor)) {
    std::cerr << "representative tensor constraint did not match\n";
    return 2;
  }

  simaai::neat::GraphOptions options;
  simaai::neat::Graph public_graph("representative-core-api", options);
  (void)public_graph;

  simaai::neat::graph::Graph runtime_graph;
  const auto input_port = runtime_graph.intern_port("input");
  const auto output_port = runtime_graph.intern_port("output");
  if (input_port == output_port || runtime_graph.port_count() != 2) {
    std::cerr << "representative runtime graph port interning failed\n";
    return 3;
  }

  const auto policy = simaai::neat::policy::make_default_policy();
  (void)policy;
  (void)sizeof(simaai::neat::Model);

  std::cout << "representative core API build ok\n";
  return 0;
}
