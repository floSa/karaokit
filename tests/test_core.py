"""Tests de la logique pure (sans dépendances lourdes : ni torch, ni ffmpeg).

Lançable avec pytest (`python -m pytest`) ou directement (`python tests/test_core.py`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke import lrc
from karaoke.align import _normalize, _rebuild_lines, interpolate_words
from karaoke.lyrics import best_search_match, clean_title
from karaoke.jobs import JobQueue, expand_audio
from karaoke.server import list_music, parse_range
from karaoke.transcribe import remove_overlaps
from karaoke.verify import MIN_OVERLAP, overlap
from karaoke.export_video import _ass_time, _karaoke_text, build_ass
from karaoke.metadata import _artist_from_path, _title_from_name
from karaoke.transcribe import Line, Word
from karaoke.utils import format_lrc_time, slugify


def test_slugify():
    assert slugify("Daft Punk — Get Lucky!") == "daft-punk-get-lucky"
    assert slugify("") == "morceau"


def test_lrc_time():
    assert format_lrc_time(75.25) == "01:15.25"


def test_parse_enhanced_lrc():
    txt = "[00:12.00]<00:12.00>Hello <00:12.50>world <00:13.00>now\n[00:20.30]Second line"
    lines = lrc.parse_lrc(txt)
    assert len(lines) == 2
    assert lines[0].text == "Hello world now"
    assert abs(lines[0].words[1].start - 12.5) < 1e-6
    assert lines[1].words[0].text == "Second line"


def test_parse_standard_lrc():
    lines = lrc.parse_lrc("[ti:X]\n[00:01.00]Line A\n[00:02.50]Line B\n")
    assert [l.text for l in lines] == ["Line A", "Line B"]


def test_write_lrc():
    built = [Line(1.0, 2.0, [Word("Bonjour", 1.0, 1.5), Word("toi", 1.5, 2.0)])]
    out = lrc.write_lrc(built, title="T", artist="A")
    assert "[00:01.00]Bonjour toi" in out


def test_align_normalize():
    assert _normalize("Été") == "ete"
    assert _normalize("l'amour") == "l'amour"
    assert _normalize("#1") == ""


def test_align_rebuild_lines_with_unalignable_word():
    line_words = [["Or", "aux", "dents", "#1"], ["Rorschach"]]
    normalized = ["or", "aux", "dents", "", "rorschach"]
    times = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.9), (2.0, 2.6)]
    lines = _rebuild_lines(line_words, normalized, times)
    assert len(lines) == 2
    assert [w.text for w in lines[0].words] == ["Or", "aux", "dents", "#1"]
    assert lines[0].words[3].start == 0.9   # '#1' hérite de la fin du voisin
    assert lines[1].words[0].start == 2.0


def test_metadata_name_parsing():
    assert _title_from_name(Path("01 - Revenons au début.flac")) == "Revenons au début"
    assert _title_from_name(Path("07. Nuits insondables.flac")) == "Nuits insondables"
    assert _title_from_name(Path("Daft Punk - Get Lucky.flac")) == "Get Lucky"
    p = Path("/x/Music/Albums/Hippie Hourrah/Expo/01 - T.flac")
    assert _artist_from_path(p) == "Hippie Hourrah"


def test_split_long_lines():
    from karaoke.transcribe import split_long_lines
    words = [Word(f"w{i}", i, i + 0.5) for i in range(24)]
    long = [Line(0, 24, words)]
    out = split_long_lines(long, max_words=9)
    assert len(out) >= 3                       # 24 mots -> plusieurs fragments
    assert all(len(l.words) <= 9 for l in out)
    assert sum(len(l.words) for l in out) == 24  # aucun mot perdu
    # une ligne courte n'est pas touchée
    short = [Line(0, 2, [Word("a", 0, 1), Word("b", 1, 2)])]
    assert len(split_long_lines(short)) == 1


def test_median_drift():
    from karaoke.pipeline import _median_drift
    a = [Line(1.0, 2, []), Line(5.0, 6, []), Line(9.0, 10, [])]
    b = [Line(1.1, 2, []), Line(4.7, 6, []), Line(9.05, 10, [])]
    assert abs(_median_drift(a, b) - 0.1) < 1e-9   # médiane de {0.1, 0.3, 0.05}
    assert _median_drift([], b) is None
    # tolère des longueurs différentes (compare par index sur le minimum)
    assert _median_drift(a, b[:1]) == 0.1 or abs(_median_drift(a, b[:1]) - 0.1) < 1e-9


def test_ass_time_and_karaoke_text():
    assert _ass_time(7.282) == "0:00:07.28"
    assert _ass_time(3661.5) == "1:01:01.50"
    words = [{"text": "Vous", "start": 7.28, "end": 7.40},
             {"text": "hante", "start": 8.40, "end": 8.90}]
    txt = _karaoke_text(words, disp_end=10.44)
    assert txt.startswith("{\\k")
    assert "Vous" in txt and "hante" in txt


def test_build_ass_structure():
    lines = [{"start": 1.0, "end": 2.0,
              "words": [{"text": "a", "start": 1.0, "end": 1.5},
                        {"text": "b", "start": 1.5, "end": 2.0}]}]
    ass = build_ass(lines, 1280, 720)
    assert "PlayResX: 1280" in ass
    assert ass.count("Dialogue:") == 1


def test_clean_title():
    assert clean_title("SOS (Album Version)") == "SOS"
    assert clean_title("Hey Jude - Remastered 2015") == "Hey Jude"
    # Parenthèses qui font partie du titre : conservées.
    assert clean_title("P.S. (I'm Still Not Over You) (Album Version)") == "P.S. (I'm Still Not Over You)"
    assert clean_title("If It's Lovin' That You Want (Pt. 2)") == "If It's Lovin' That You Want (Pt. 2)"


def test_best_search_match_requires_duration():
    results = [
        {"duration": 180.0, "syncedLyrics": "[00:01.00]a"},
        {"duration": 227.0, "plainLyrics": "plain"},
        {"duration": 226.0, "syncedLyrics": "[00:01.00]b"},
    ]
    assert best_search_match(results, None) is None  # pas de durée : pas de pari
    assert best_search_match(results, 226.9)["syncedLyrics"] == "[00:01.00]b"  # synchronisé d'abord
    assert best_search_match(results, 300.0) is None


def test_lyrics_overlap_rejects_other_song():
    heard = "you promised me good days but all are like sunday for my words to come out right my evil needs your inside"
    right = "You promised me good days\nBut all are like Sunday\nFor my words to come out right\nMy evil needs your inside"
    wrong = "Heute morgen wacht ich dann auf\nAlles ganz still und leise\nNur der Punk ist auf dem Weg nach Haus"
    assert overlap(heard, right) >= MIN_OVERLAP
    assert overlap(heard, wrong) < MIN_OVERLAP
    assert overlap("la la", right) is None  # trop peu de mots pour juger


def test_interpolate_words():
    line = interpolate_words(["a", "longword"], 10.0, 20.0)
    assert line.start == 10.0 and len(line.words) == 2
    assert line.words[0].end == line.words[1].start  # enchaînés
    assert line.words[1].end - line.words[1].start > line.words[0].end - line.words[0].start
    assert line.words[-1].end <= 20.0


def test_remove_overlaps():
    lines = [
        Line(0, 3, [Word("a", 0.0, 1.5), Word("b", 1.0, 3.0)]),
        Line(2.5, 4, [Word("c", 2.5, 4.0)]),
    ]
    remove_overlaps(lines)
    words = [w for l in lines for w in l.words]
    assert all(x.end <= y.start for x, y in zip(words, words[1:]))
    assert lines[0].end == words[1].end


def test_parse_range():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-", 100) == (0, 99)
    assert parse_range("bytes=10-19", 100) == (10, 19)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=50-500", 100) == (50, 99)
    assert parse_range("bytes=100-", 100) is False
    assert parse_range("bytes=0-1,5-6", 100) is None


def test_list_music_stays_inside_roots(tmp_path=None):
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "Album").mkdir()
    (root / "Album" / "01 - Titre.flac").write_bytes(b"")
    (root / "Album" / "cover.jpg").write_bytes(b"")
    (root / ".cache").mkdir()
    listing = list_music([root], str(root))
    assert [d["name"] for d in listing["dirs"]] == ["Album"] and listing["parent"] is None
    album = list_music([root], str(root / "Album"))
    assert [f["name"] for f in album["files"]] == ["01 - Titre.flac"]  # images ignorées
    assert album["parent"] == str(root)
    for escape in ("/etc", str(root / ".." )):
        try:
            list_music([root], escape)
            raise AssertionError("sortie des racines acceptée")
        except PermissionError:
            pass
    assert expand_audio([root / "Album"]) == [root / "Album" / "01 - Titre.flac"]


def test_job_queue_dedupe_and_cancel():
    q = JobQueue(Path("/tmp"))
    q._thread = object()  # pas de thread de fond : on teste la seule logique de file
    a = q.submit([Path("/m/a.flac"), Path("/m/b.flac"), Path("/m/a.flac")])
    assert [j.name for j in a] == ["a", "b"]
    assert q.submit([Path("/m/a.flac")]) == []  # déjà en attente
    assert q.cancel(a[0].id) and not q.cancel(a[0].id)
    assert [j["status"] for j in q.snapshot()] == ["cancelled", "queued"]
    assert q.clear_finished() == 1 and len(q.snapshot()) == 1


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} tests OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
