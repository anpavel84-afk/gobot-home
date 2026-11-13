"""Deterministic microphone-free frontend probe, shared with the S3 boot self-test."""
from pymicro_features import MicroFrontend

def fingerprint():
    state = 17
    digest = 2166136261
    front = MicroFrontend()
    rows = 0
    for frame in range(100):
        pcm = bytearray()
        for i in range(160):
            state = (1664525 * state + 1013904223) & 0xffffffff
            pcm.extend(((state >> 19)-4096).to_bytes(2,"little",signed=True))
        values = front.process_samples(bytes(pcm)).features
        rows += bool(values)
        for x in values:
            digest = ((digest ^ round(x*25.6))*16777619) & 0xffffffff
    return rows, digest
if __name__ == "__main__":
    print(*fingerprint())
