// HOST-B native-only regression; tests no-microphone/zero-cost handshake logic.
#include "pcm_tap_gate.hpp"
#include <cassert>
#include <cstdint>
using namespace gobot_wn10;
int main() {
    SourceGate g;
    assert(g.active() == Source::PLAN_STREAM);
    assert(g.allow_plan_detection());
    assert(g.select(Source::ESP_LOCAL_WAKENET10));
    assert(!g.allow_plan_detection());
    const auto generation = g.generation();
    assert(!g.on_local_detection(false, generation, 512));  // demo is forbidden
    assert(g.on_local_detection(true, generation, 512));    // approved future model only
    assert(!g.on_local_detection(true, generation, 1024));  // duplicate blocked
    g.phase(Phase::LISTENING);
    assert(!g.select(Source::PLAN_STREAM)); // busy switch forbidden
    g.phase(Phase::SPEAKING);
    assert(!g.select(Source::PLAN_STREAM));
    g.phase(Phase::STOP_PENDING);
    assert(!g.select(Source::PLAN_STREAM));
    g.phase(Phase::IDLE);
    g.set_pending(true);
    assert(!g.select(Source::PLAN_STREAM));
    g.set_pending(false);
    assert(g.select(Source::PLAN_STREAM));
    assert(g.allow_plan_detection());
    assert(!g.on_local_detection(true, generation, 2048)); // wrong source / generation
    g.reset_stream_epoch();
    assert(g.allow_plan_detection());

    PcmTap tap(512);
    assert(tap.valid());
    int16_t input[960]{};
    size_t fired = 0;
    uint64_t last_end = 0;
    auto got_chunk = [&](const int16_t *, size_t n, uint64_t end) {
        assert(n == 512);
        if (fired) assert(end > last_end);
        last_end = end;
        ++fired;
    };
    assert(tap.feed(input, 960, 0, got_chunk));
    assert(fired == 1 && tap.buffered() == 448 && last_end == 512);
    assert(tap.feed(input, 960, 960, got_chunk));
    assert(fired == 3 && tap.buffered() == 384 && last_end == 1536);
    assert(!tap.feed(input, 960, 99999, got_chunk)); // discontinuity fail closed
    assert(tap.buffered() == 0);
    assert(!PcmTap(4096).valid());
    assert(!tap.feed(input, 961, 0, got_chunk));
    return 0;
}
