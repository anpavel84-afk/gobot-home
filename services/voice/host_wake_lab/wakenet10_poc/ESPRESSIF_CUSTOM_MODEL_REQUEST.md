# Draft inquiry to Espressif — NOT SENT

To: sales@espressif.com
Subject: WakeNet10 custom Russian wake word "Мо́ника" for ESP32-S3 — evaluation and quotation

Hello Espressif Speech Recognition Team,

We are developing GoBot, an embedded voice-assistant device using ESP32-S3
(16 MB Flash, 8 MB PSRAM, ES8311 microphone/audio codec, a single 16-kHz
mono signed-PCM microphone producer). Our pinned build environment is
ESP-IDF 6.0.1 and ESP-SR 2.6.2.

We are evaluating the official WakeNet10 Russian demo model
"wn10_ru_privetesp" to validate the engine. Our intended production wake
phrase is a **different** three-syllable Russian name:

  Cyrillic spelling: Мо́ника (without combining mark: Моника)
  Transliteration: Monika
  Pronunciation: MO-ni-ka, stress on the FIRST syllable.

Could you please advise:

1. Does a licensed official WakeNet10 model for this exact Russian phrase
   already exist? Is a free, time-limited technical evaluation build available?
2. Is Russian WakeNet10 TTS-only customization commercially available today,
   without collecting or transferring private human voice recordings? Can we
   receive a no-cost feasibility assessment or a free noncommercial demo?
3. If customization is needed, what are the one-time model/training fee,
   any minimum order or commercial usage thresholds, deliverable format,
   modification rights, and redistribution/commercial licensing terms?
   Please confirm whether per-device and annual royalties are indeed zero.
4. Please quote expected end-to-end lead time, including any TTS-only
   adaptation, model testing and requested iterations. We understand your
   general documentation describes roughly 2–3 weeks AFTER a corpus is
   ready for the data-based methods; does this apply to TTS-only Russian?
5. Will the model be compatible with esp-sr 2.6.2, ESP-IDF 6.0.1 and
   1-channel WakeNet10 DET_MODE_90 on ESP32-S3? What are its partition
   Flash requirements, peak internal RAM / PSRAM, CPU load and estimated
   wake recall / false-activation rates in real Russian home/TV speech?
6. Are there license restrictions for distributing the model as part of
   a commercial product? Please specify the required license notices,
   whether a customer may store the weights in their own firmware, and
   update/maintenance obligations.

Our existing device partition table currently has no "model" partition;
we are evaluating partition-layout options without modifying a deployed
device. We are NOT placing a paid order in this email. No personal recordings,
microphone audio, secrets, hardware identities or customer data are attached.

Thank you for your guidance.

GoBot engineering team
