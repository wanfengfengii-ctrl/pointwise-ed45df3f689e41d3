from dataclasses import asdict, dataclass

from contract import fields
from program.audio import AudioClip, build_audio_catalog
from program.rules import GroupRules, compile_groups


@dataclass(frozen=True)
class ShowDraft:
    audio: dict[str, AudioClip]
    groups: dict[str, GroupRules]

    def payload(self):
        return {
            'audio': [asdict(clip) for clip in self.audio.values()],
            'groups': [asdict(group) for group in self.groups.values()],
        }


def build_draft(payload):
    fields(payload, ('audio', 'groups'))
    audio = build_audio_catalog(payload['audio'])
    return ShowDraft(audio, compile_groups(payload['groups'], audio))
