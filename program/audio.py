from dataclasses import dataclass

from contract import array, fail, fields, integer, text


@dataclass(frozen=True)
class AudioClip:
    audio_id: str
    name: str
    length_ticks: int


def build_audio_catalog(entries):
    catalog = {}
    for entry in array(entries, 'audio'):
        fields(entry, ('audio_id', 'name', 'length_ticks'))
        audio_id = text(entry['audio_id'], 'audio_id')
        if audio_id in catalog:
            fail(400, 'duplicate_audio', f'Audio {audio_id} appears twice')
        catalog[audio_id] = AudioClip(
            audio_id, text(entry['name'], 'name'), integer(entry['length_ticks'], 'length_ticks')
        )
    return catalog
