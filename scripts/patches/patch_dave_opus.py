#!/usr/bin/env python3
"""
DAVE Decryption Patch for discord-ext-voice-recv opus.py

Discord made DAVE (Discord Audio Video Encryption) mandatory for voice
channels in April 2026. The installed discord-ext-voice-recv 0.5.3a180
from GitHub main did NOT include the DAVE decryption fix from PR #54.

This patch adds:
1. _dave_decrypt() — decrypts DAVE-encrypted audio using davey.DaveSession.decrypt()
2. _dave_log() — file-based debug logging to /tmp/dave_debug.log
3. _safe_decode() — wraps Opus decoder to handle invalid data gracefully
   (3-byte DAVE transition markers, corrupted packets from DecryptionFailed fallback)
4. DecryptionFailed(UnencryptedWhenPassthroughDisabled) exception handling

Apply with: python3 scripts/patches/patch_dave_opus.py
Re-apply after venv rebuild or discord-ext-voice-recv reinstall.

Context: Admiral Schubert voice bot — Project Tango
"""
import sys
import os

OPUS_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'backend', 'venv',
    'lib', 'python3.14', 'site-packages',
    'discord', 'ext', 'voice_recv', 'opus.py'
)
OPUS_PATH = os.path.normpath(OPUS_PATH)

DAVE_IMPORT = '''try:
    from davey import MediaType as DaveMediaType
    _has_dave = True
except ImportError:
    _has_dave = False'''

DAVE_METHODS = '''    _dave_count = 0

    def _dave_log(self, msg):
        with open("/tmp/dave_debug.log", "a") as f:
            f.write(msg + "\n")

    def _dave_decrypt(self, packet) -> bytes:
        """Decrypt DAVE-encrypted audio data if a DAVE session is active."""
        if not _has_dave or not packet:
            return packet.decrypted_data
        try:
            vc = self.sink.voice_client
            dave_session = vc._connection.dave_session
            PacketDecoder._dave_count += 1
            n = PacketDecoder._dave_count
            if n <= 20 or n % 200 == 0:
                self._dave_log("#%d: session=%s ready=%s payload=%d raw_len=%d passthrough=%s" % (
                    n, dave_session is not None,
                    dave_session.ready if dave_session else None,
                    packet.payload, len(packet.decrypted_data),
                    dave_session.can_passthrough if dave_session else None))
            if dave_session is None:
                return packet.decrypted_data
            if not dave_session.ready:
                return packet.decrypted_data
            if packet.payload != 120:
                return packet.decrypted_data
            user_id = self._cached_id
            if user_id is None:
                user_id = vc._get_id_from_ssrc(self.ssrc)
                self._cached_id = user_id
            if user_id is None:
                return packet.decrypted_data
            decrypted = dave_session.decrypt(
                user_id,
                DaveMediaType.audio,
                bytes(packet.decrypted_data)
            )
            if n <= 20 or n % 200 == 0:
                self._dave_log("#%d: user_id=%s decrypted_len=%d raw_len=%d" % (
                    n, user_id,
                    len(decrypted) if decrypted else 0,
                    len(packet.decrypted_data)))
            return decrypted if decrypted else packet.decrypted_data
        except Exception as e:
            self._dave_log("EXCEPTION #%d: %s" % (PacketDecoder._dave_count, e))
            return packet.decrypted_data
'''

SAFE_DECODE_PACKET = '''    def _decode_packet(self, packet: AudioPacket) -> Tuple[AudioPacket, bytes]:
        assert self._decoder is not None

        SILENCE_PCM = b'\\x00' * 3840

        def _safe_decode(data, fec=False):
            """Decode Opus data with full error handling."""
            try:
                if data is None:
                    return self._decoder.decode(None, fec=fec)
                if len(data) < 3:
                    return SILENCE_PCM
                return self._decoder.decode(data, fec=fec)
            except Exception as e:
                self._dave_log("OPUS_DECODE_ERROR: %s data_len=%d" % (e, len(data) if data else 0))
                return SILENCE_PCM

        # Decode as per usual
        if packet:
            opus_data = self._dave_decrypt(packet)
            pcm = _safe_decode(opus_data, fec=False)
            return packet, pcm

        # Fake packet, need to check next one to use fec
        next_packet = self._buffer.peek_next()

        if next_packet is not None:
            nextdata: bytes = self._dave_decrypt(next_packet)  # type: ignore

            log.debug(
                "Generating fec packet: fake=%s, fec=%s",
                packet.sequence,
                next_packet.sequence,
            )
            pcm = _safe_decode(nextdata, fec=True)

        # Need to drop a packet
        else:
            pcm = _safe_decode(None, fec=False)

        return packet, pcm'''


def apply_patch():
    if not os.path.exists(OPUS_PATH):
        print(f"ERROR: opus.py not found at {OPUS_PATH}")
        sys.exit(1)

    with open(OPUS_PATH, 'r') as f:
        content = f.read()

    changes = 0

    # 1. Add DAVE import if not present
    if '_has_dave' not in content:
        content = content.replace(
            'from discord.opus import Decoder',
            'from discord.opus import Decoder\n\n' + DAVE_IMPORT
        )
        changes += 1
        print("  + Added DAVE import")
    else:
        print("  = DAVE import already present")

    # 2. Add _dave_decrypt and _dave_log methods before _decode_packet
    if '_dave_decrypt' not in content:
        content = content.replace(
            '    def _decode_packet(',
            DAVE_METHODS + '\n    def _decode_packet('
        )
        changes += 1
        print("  + Added _dave_decrypt() and _dave_log() methods")
    else:
        print("  = _dave_decrypt() already present")

    # 3. Replace _decode_packet with _safe_decode version
    old_start = content.find('    def _decode_packet(self, packet: AudioPacket) -> Tuple[AudioPacket, bytes]:')
    if old_start >= 0:
        search_start = old_start + 50
        end = content.find('\n    def ', search_start)
        if end < 0:
            end = content.find('\nclass ', search_start)
        if end < 0:
            end = len(content)

        old_method = content[old_start:end]
        if '_safe_decode' not in old_method:
            content = content[:old_start] + SAFE_DECODE_PACKET + content[end:]
            changes += 1
            print("  + Replaced _decode_packet with _safe_decode version")
        else:
            print("  = _safe_decode already present in _decode_packet")
    else:
        print("  ! Could not find _decode_packet method")

    if changes > 0:
        with open(OPUS_PATH, 'w') as f:
            f.write(content)
        print(f"\nPATCH APPLIED: {changes} change(s) to {OPUS_PATH}")
    else:
        print("\nNo changes needed — patch already applied.")


if __name__ == '__main__':
    print(f"Patching: {OPUS_PATH}")
    apply_patch()