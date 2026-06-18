#include <cstddef>
#include <cstdint>

extern "C" void shisa_fuzz_frame_decode(const uint8_t *data, size_t size);
extern "C" void shisa_fuzz_context_input(const uint8_t *data, size_t size);

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  if (size == 0) {
    shisa_fuzz_frame_decode(data, size);
    return 0;
  }

  const uint8_t selector = data[0] & 1;
  const uint8_t *payload = data + 1;
  const size_t payload_size = size - 1;
  if (selector == 0) {
    shisa_fuzz_frame_decode(payload, payload_size);
  } else {
    shisa_fuzz_context_input(payload, payload_size);
  }
  return 0;
}
