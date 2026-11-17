# HOST-B experimental WakeNet10 -> HOST-A handoff (NO FLASH)

**Owner latest instruction (#6935913449): HOST-A alone owns PC Vosk/T-one, cloud STT, Brain, local/server wake and physical ESP32 integration. HOST-B is only ESP_LOCAL research. No HOST-D.**

**This is a review proposal, not a change to HOST-A.**
The current installed RC1-r3 does not contain the WakeNet10 models or local
wake control. Using this proposal requires A-owned source integration, full
regression, a separate permitted app-only image, model storage plan, and a
distinct physical flash approval. Neither test harness nor model file changes
the current running server Monika.

## One microphone reader and one wake owner

- Keep HOST-A's single existing ES8311/I2S audio producer. ESP-SR must NOT
  add another I2S microphone driver, task, or reader.
- At the established 16kHz PCM16 microphone tap BEFORE Opus encoding,
  copy at most the existing 960-sample (60ms) frame into PcmTap.
- WakeNet10's get_samp_chunksize() determines its actual frame size; bridge
  re-chunks 960-source-frames into exactly that native number, and fails
  closed on gaps/incorrect size. This is not a 60ms resampling operation.
- ESP-SR direct WN interface can run DET_MODE_90 (mono); no duplicate AEC.
  HOST-A's existing AEC/Opus, codec, Wi-Fi and UI remain sole owners.
  Running CPU/heap cost ON THE ACTUAL Spotpear is NOT measured yet.
- The current PC Vosk remains PLAN_STREAM unchanged and is the ONLY active
  source until full Monika custom model and acoustic acceptance.
- A exposes a volatile enum PLAN_STREAM / ESP_LOCAL_WAKENET10, switchable
  only IDLE, with no outstanding turn, playback, mute or Stop.
- Only one source produces activation events; reset wake latch and epoch
  only at a verified stream boundary. Never permit simultaneous sources.
- No changes to NVS, financial ledgers, Brain, OTA, keys or gateway config.

## New transport request: A implementation required

Do NOT fake a real physical touch. Existing A server only allows the
gobot_host_touch event, not a true ESP local wake. A should explicitly
review a narrowly scoped, authenticated protocol extension:

  gobot_host_local_wake:
    session_id: current authenticated existing HOST session ID
    epoch: current authenticated stream epoch
    origin: ESP_LOCAL_WAKENET10
    model_id: exact, signed/verified "monika" model manifest identifier
    end_sample_index: the same source producer stream's sample-end index
    generation: volatile source-selection generation

A must validate fresh epoch/generation/source, monotonic source sample,
current IDLE, no pending playback/Stop and approved model ID, then call the
EXISTING HostCore.activate("host_wake"). It must not simultaneously run
PLAN_STREAM Vosk detector. Pre-roll stays on PLAN (A-owned 2s RAM buffer)
and upload continues before/after wake so the first words of the question
are not clipped. A owns cue, screen, listener, response, mute and Stop.

**THIS EVENT IS NOT SUPPORTED BY RC1-r3 NOW.** HOST-A must implement it.
The unmodified r3 cannot be locally awakened by the demo weights.

## Model and policy gate

The official shipped wn10_ru_privetesp weights recognize "Привет ESP",
not "Моника". The proof of concept has no real local Monika model,
and the demo must NEVER send an activation. Production hardware local
mode requires: verifiable official weights plus redistribution permission,
runtime confidence/false wake evaluation, A integration, memory/flash review,
AND explicit release authorization. Until then: PLAN_STREAM only.

Native tests are under test_pcm_tap_gate.cpp, using the host C++ compiler.
No UART, peripheral, production input or paid voice session is involved.
