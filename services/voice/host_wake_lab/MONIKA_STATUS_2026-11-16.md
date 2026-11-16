# GoBot HOST-B: Owner selected «Моника» — 16 November 2026

User selected **Моника** following subjective live free dictation on PLAN. This is useful evidence but is NOT an acoustic wake acceptance measurement. Project remains GoBot.

## Code and vocabulary verified

The installed Vosk small Russian 0.22 model returns word ID **57908** for exactly "моника". Some morphological case forms occur in the lexicon but are NOT aliases. The wake policy selects one and only one initial Cyrillic word "моника" with explicit candidate ID "monika"; it cannot be activated by substring matches for "монитор", "моник", "мониторинг", "Моня" or "гоби". It requires two temporally separated ASR updates and accepts exact mono signed PCM16 16kHz frames of up to 960 samples.

HOST-B monika_bridge.py supplies HOST-A's canonical AudioChunk -> WakeEvent adapter. By default activation_approved=False and it returns no events even if Monika is recognized. A deliberately finite isolated A-owned test may set two distinct gates (allow_experimental_events and isolated_hardware_test) to allow the existing HOST-A HostCore to receive a wake. Neither flag is persisted, and it is explicitly forbidden in the ordinary production gateway without separate acceptance.

## Owner present PC microphone test

On the PLAN desktop the optional local file is:
C:\Users\PLAN\gobot\HOST-B-lab\START_MONIKA_WAKE_TEST.cmd

The owner physically types YES-PC-MIC at the PLAN console. The test evaluates three positive utterances (Monika alone, Monika+weather without a pause, Monika+time without a pause), and five negative utterances (monitor, monik, Monya, conversation mentioning Monica, unrelated room talk), plus optional 30 seconds of REAL TV. Uses Windows MME input device 1, Vosk as LIVE primary, T-one same RAM PCM SHADOW replay, Zipformer diagnostic console. Output is local event cue and numeric/count metadata only; no microphone audio, personal transcript, or cloud upload. The Owner's earlier subjective dictation is not automatically imported as a pass.

**Monika human wake result NOT YET MEASURED at this checkpoint**. True wake detection and missed rates, real TV/background false events/hour, and name-end P50/P95 need a personally confirmed trial. No number is inferred from dictionary membership or artificial event tests. A frequent name in a TV programme can be spoken without addressing the assistant: it is a meaningful negative test.

## Physical hardware: A owns release

HOST-A separately confirmed real physical ESP32-S3 app-only RC1 r3 installed (0.4.13-dev-host-a-rc1-r3), real Opus microphone stream to PLAN, and local Opus packets sent back to device. It did NOT certify human speech intelligibility, genuine meaningful Brain response, 30-minute Wi-Fi soak, touch/volume human acceptance or NVS bitwise preservation. The A worktree was actively using its own isolated test listener (port 18799) and COM3 while B developed Monika. HOST-B did not touch A files, A listener, COM3, working gateway or firmware.

B-only monika_host_pilot.py can run a finite free private-LAN test listener using A's existing Gateway, TLS certificates, enrollment and HostCore READ-ONLY (A source unmodified), when and ONLY when A is not already testing on port 18799. It refuses any other port or session over 180 seconds, blocks all paid OpenAI and Brain calls, never persists room audio or transcripts, and requires a fresh local YES-MONIKA-PILOT confirmation to emit wake events. It NEVER toggles COM3, so the existing A-owned HOST-ON / HOST-OFF procedure must be coordinated separately. Do not take control of a parallel HOST-A hardware trial.

A's main Python environment supplies PyAV and httpx; for the isolated pilot, it reads only the already installed Vosk Python package from B's separate venv (same Python ABI), without installing dependencies or changing production environments. A-only test preflight was observed to load the actual model and find Monika vocabulary without launching a listener or opening microphone/UART.

### Read-only preflight

Run with the existing MAIN Python environment and B source import path from PowerShell on PLAN:

    $env:PYTHONPATH='C:\Users\PLAN\gobot\GoBotHome-wake-lab'
    & 'C:\Users\PLAN\gobot\GoBotHome\.venv\Scripts\python.exe' -m services.voice.host_wake_lab.monika_host_pilot --models-root 'C:\Users\PLAN\gobot\HOST-B-lab\models' --preflight-only --seconds 120

### No-mic tests

    Set-Location 'C:\Users\PLAN\gobot\GoBotHome-wake-lab'
    & 'C:\Users\PLAN\gobot\HOST-B-lab\.venv\Scripts\python.exe' -m unittest discover -s tests -p 'test_host_wake_lab_*.py' -q

This work is restricted to HOST-B namespaced files and tests. No hardware flash, paid API, server process or production gateway change. Safe publication: B branch feat/host-wake-lab-public, draft PR #9. Await separate human acoustic trial and A-owned physical authorization before any full release.

**Gates:** SOURCE_IMPLEMENTED, VOSK_VOCAB_VERIFIED, MODEL_RUNTIME_PREFLIGHT_PASS, LIVE_MONIKA_HUMAN_NOT_YET_ACCEPTED, HARDWARE_MONIKA_WAKE_NOT_RUN, BRAIN_E2E_NOT_DONE, PAID_CALLS=0. No master merge or production activation.
