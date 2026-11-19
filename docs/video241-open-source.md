# Video 241: bounded legacy-server tooling

Owner request and pause ledger: [Issue 188](https://github.com/zurvanproject/zohraya/issues/188).

The chosen server component is portable FFmpeg 4.2.2, taken from the immutable
`imageio-ffmpeg==0.4.9` Windows x64 wheel. The archive and extracted executable
have separate SHA256 pins. This compatibility-oriented version is intentionally
isolated under `%PROGRAMDATA%/NasurayaBridge/video241_v1`. It is for trusted
project-generated media only. It does not provide a text-to-video model.
No system PATH, existing Python packages, bridge service, or task schedule changes.

The single-file bridge job downloads at most 22,619,540 bytes with a deadline,
reads two exact archive members without path extraction, verifies the executable,
encodes a one-second H.264/yuv420p MP4 and decodes it, then records a local receipt.
An identical verified executable is reused on replay. Failure does not count as
installation: the JSON summary explicitly says `VIDEO241=FAILED`.

CPU count, total RAM and numeric NVIDIA VRAM (or UNKNOWN) are the only published
hardware fields. No host name, IP, user name, keys or file contents are reported.
The legacy Windows Server 2012 R2 target still requires its own successful receipt;
passing Windows 2022 CI does not establish compatibility on that VPS.

Open-source generative motion is attempted separately using the public free Wan
2.2 demo. No paid inference endpoint or model download is authorized. Wan 2.2's
official 5B example requires at least 24GB GPU VRAM, so a GPU install on the VPS
cannot be justified from its old Python/Windows receipt alone.

## Execution and pause evidence

- Prior unacknowledged research/social queue entries were made non-executable;
  their original text is preserved in Issue 188.
- Graceful STOP request: Issue 149 comment 6780629913. A queued request is not a
  server acknowledgement. Do not kill unrelated processes or stop Bridge itself.
- Do not resubmit uncertain old work until its local journal has been checked.
- No merge, paid API, Moltbook post, or automatic research restart is part of this change.

## Validation

Run `python -m unittest discover -s tools/bridge_jobs -p test_video241_install.py -v`.
The focused workflow runs those integrity tests on Linux and Windows and performs
real pinned-binary encode/decode on Windows 2022 in a temporary CI directory.

## Sources

- https://pypi.org/project/imageio-ffmpeg/0.4.9/
- https://github.com/imageio/imageio-ffmpeg
- https://github.com/Wan-Video/Wan2.2
- https://huggingface.co/spaces/zerogpu-aoti/wan2-2-fp8da-aoti-faster
