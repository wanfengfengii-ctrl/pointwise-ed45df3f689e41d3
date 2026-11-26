from dataclasses import dataclass

from narration.playback import PlayResult


@dataclass(frozen=True)
class ReportEntry:
    result: PlayResult

    def payload(self):
        entry = self.result.payload()
        del entry['session_id']
        return entry


def build_timeline(results):
    ordered = sorted(results, key=lambda result: (result.tick, result.group_id))
    return tuple(ReportEntry(result) for result in ordered)
