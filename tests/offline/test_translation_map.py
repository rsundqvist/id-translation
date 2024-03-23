import pandas as pd
import pytest
from id_translation.offline import TranslationMap


def test_copy(translation_map):
    c = translation_map.copy()

    assert c.fmt == translation_map.fmt
    assert c.default_fmt == translation_map.default_fmt
    assert c.default_fmt_placeholders == translation_map.default_fmt_placeholders
    assert len(c) == len(translation_map)
    assert all(left == right for left, right in zip(c, translation_map))


def test_props(translation_map):
    assert sorted(translation_map.sources) == ["name_basics", "title_basics"]
    assert sorted(translation_map.names) == ["firstTitle", "nconst"]
    assert sorted(translation_map) == ["firstTitle", "name_basics", "nconst", "title_basics"]


class TestToFromPandas:
    @pytest.fixture(autouse=True)
    def _set_translation_map(self, translation_map):
        self._tmap = translation_map

    def test_to_pandas(self):
        frames = self._tmap.to_pandas()
        self.verify_sources_and_placeholders(frames)

    def test_from_pandas(self):
        frames = self._tmap.to_pandas()
        from_pandas = TranslationMap.from_pandas(frames).to_pandas()
        self.verify_sources_and_placeholders(from_pandas)

        for source in self._tmap.sources:
            pd.testing.assert_frame_equal(frames[source], from_pandas[source], obj=f"to_pandas[{source!r}]")

    def test_sanity(self):
        frames = self._tmap.to_pandas()
        from_pandas = TranslationMap.from_pandas(frames).to_pandas()

        # Sanity check -- this should fail
        source = "title_basics"
        frames[source].loc[15, "id"] = -1
        with pytest.raises(AssertionError) as e:
            pd.testing.assert_frame_equal(frames[source], from_pandas[source], obj=f"to_pandas[{source!r}]")

        assert f'to_pandas[{source!r}].iloc[:, 5] (column name="id") are different' in str(e.value)

    def test_equal_to_dicts_format(self):
        frames = self._tmap.to_pandas()
        dicts = self._tmap.to_dicts()

        assert sorted(frames) == sorted(dicts), "source mismatch"

        for source, frame in frames.items():
            assert dicts[source] == frame.to_dict(orient="list"), f"{source=}"

    def verify_sources_and_placeholders(self, frames):
        expected = self._tmap.placeholders

        assert sorted(frames) == sorted(expected), "source mismatch"
        for source, placeholders in expected.items():
            assert sorted(frames[source].columns) == sorted(placeholders), f"placeholder mismatch: {source=}"


def test_to_translations(translation_map):
    actual = translation_map.to_translations(fmt="{id}:{name!r}")
    assert actual == {
        "name_basics": {
            1: "1:'Fred Astaire'",
            2: "2:'Lauren Bacall'",
            4: "4:'John Belushi'",
            5: "5:'Ingmar Bergman'",
            6: "6:'Ingrid Bergman'",
            7: "7:'Humphrey Bogart'",
            8: "8:'Marlon Brando'",
            9: "9:'Richard Burton'",
            10: "10:'James Cagney'",
            11: "11:'Gary Cooper'",
            12: "12:'Bette Davis'",
            13: "13:'Doris Day'",
            14: "14:'Olivia de Havilland'",
            15: "15:'James Dean'",
            16: "16:'Georges Delerue'",
            17: "17:'Marlene Dietrich'",
            18: "18:'Kirk Douglas'",
            19: "19:'Federico Fellini'",
            20: "20:'Henry Fonda'",
            21: "21:'Joan Fontaine'",
            22: "22:'Clark Gable'",
            23: "23:'Judy Garland'",
            24: "24:'John Gielgud'",
            25: "25:'Jerry Goldsmith'",
            26: "26:'Cary Grant'",
            27: "27:'Alec Guinness'",
            28: "28:'Rita Hayworth'",
            29: "29:'Margaux Hemingway'",
            30: "30:'Audrey Hepburn'",
            31: "31:'Katharine Hepburn'",
            32: "32:'Charlton Heston'",
            33: "33:'Alfred Hitchcock'",
            34: "34:'William Holden'",
            35: "35:'James Horner'",
            36: "36:'Buster Keaton'",
            37: "37:'Gene Kelly'",
            38: "38:'Grace Kelly'",
            39: "39:'Deborah Kerr'",
            40: "40:'Stanley Kubrick'",
            41: "41:'Akira Kurosawa'",
            42: "42:'Alan Ladd'",
            43: "43:'Veronica Lake'",
            44: "44:'Burt Lancaster'",
            45: "45:'Bruce Lee'",
            46: "46:'Vivien Leigh'",
            48: "48:'Peter Lorre'",
            49: "49:'Henry Mancini'",
            50: "50:'Groucho Marx'",
            51: "51:'James Mason'",
            52: "52:'Marcello Mastroianni'",
            53: "53:'Robert Mitchum'",
            1380: "1380:'Jim Hutton'",
            54: "54:'Marilyn Monroe'",
            55: "55:'Alfred Newman'",
            56: "56:'Paul Newman'",
            57: "57:'David Niven'",
            58: '58:"Maureen O\'Hara"',
            59: "59:'Laurence Olivier'",
            60: "60:'Gregory Peck'",
            61: "61:'Tyrone Power'",
            62: "62:'Elvis Presley'",
            63: "63:'Anthony Quinn'",
            64: "64:'Edward G. Robinson'",
            65: "65:'Nino Rota'",
            66: "66:'Jane Russell'",
            67: "67:'Miklós Rózsa'",
            68: "68:'Randolph Scott'",
            69: "69:'Frank Sinatra'",
            70: "70:'Max Steiner'",
            71: "71:'James Stewart'",
            72: "72:'Elizabeth Taylor'",
            73: "73:'Shirley Temple'",
            74: "74:'Gene Tierney'",
            75: "75:'Spencer Tracy'",
            76: "76:'François Truffaut'",
            77: "77:'Franz Waxman'",
            78: "78:'John Wayne'",
            80: "80:'Orson Welles'",
            81: "81:'Natalie Wood'",
            82: "82:'Victor Young'",
            86: "86:'Louis de Funès'",
            88: "88:'Aleksey Korenev'",
            89: "89:'Richard Paul'",
            122: "122:'Charles Chaplin'",
            125: "125:'Sean Connery'",
            127: "127:'Wes Craven'",
            135: "135:'John Denver'",
            180: "180:'David Lean'",
            200: "200:'Bill Paxton'",
            203: "203:'River Phoenix'",
            245: "245:'Robin Williams'",
            248: "248:'Edward D. Wood Jr.'",
            252: "252:'Robert Ellis'",
            253: "253:'Robert Ellis'",
            265: "265:'Robert Altman'",
            277: "277:'Richard Attenborough'",
            290: "290:'John Barry'",
            303: "303:'Honor Blackman'",
            305: "305:'Mel Blanc'",
            308: "308:'Ernest Borgnine'",
        },
        "title_basics": {
            25509: "25509:'Les Misérables'",
            35803: "35803:'The German Weekly Review'",
            38276: "38276:'You Are an Artist'",
            39120: "39120:'Americana'",
            39121: "39121:'Birthday Party'",
            39123: "39123:'Kraft Theatre'",
            39125: "39125:'Public Prosecutor'",
            40021: '40021:"Actor\'s Studio"',
            40022: "40022:'The Adventures of Oky Doky'",
            40023: "40023:'The Alan Dale Show'",
            40024: "40024:'America Song'",
            40026: '40026:"America\'s Town Meeting"',
            40027: "40027:'The Arrow Show'",
            40028: "40028:'Talent Scouts'",
            40030: "40030:'Author Meets the Critics'",
            40032: "40032:'The Bigelow Show'",
            40033: "40033:'Break the $250,000 Bank'",
            40034: "40034:'Candid Camera'",
            40036: "40036:'The Chevrolet Tele-Theatre'",
            40037: "40037:'The Fashion Story'",
            40038: "40038:'The Growing Paynes'",
            40039: "40039:'Hollywood Screen Test'",
            40041: "40041:'The Milton Berle Show'",
            40042: "40042:'The Morey Amsterdam Show'",
            40045: "40045:'Okay, Mother'",
            40048: '40048:"Perry Como\'s Kraft Music Hall"',
            40049: "40049:'The Philco Television Playhouse'",
            40050: "40050:'Picture This'",
            40051: "40051:'Studio One'",
            40053: "40053:'The Ed Sullivan Show'",
            40057: "40057:'We, the People'",
            40058: "40058:'Welcome Aboard'",
            40062: "40062:'Young Broadway'",
            40995: "40995:'The Al Morgan Show'",
            40996: "40996:'The Aldrich Family'",
            41002: "41002:'Arthur Godfrey and His Friends'",
            41005: "41005:'Believe It or Not'",
            41007: "41007:'The Big Story'",
            41009: "41009:'Your Big Moment'",
            41010: "41010:'Blues by Bargy'",
            41014: "41014:'Captain Video and His Video Rangers'",
            41015: "41015:'Cavalcade of Stars'",
            41016: "41016:'The Eyes Have It'",
            41018: "41018:'Colgate Theatre'",
            41019: "41019:'A Couple of Joes'",
            41020: "41020:'Easy Aces'",
            41021: "41021:'The Ed Wynn Show'",
            41022: "41022:'The Fifty-Fourth Street Revue'",
            41023: "41023:'Fireside Theatre'",
            41024: "41024:'The Ford Television Theatre'",
            41025: "41025:'The Front Page'",
            41026: "41026:'Front Row Center'",
            41027: "41027:'The Goldbergs'",
            41029: "41029:'Hollywood House'",
            41030: "41030:'Hopalong Cassidy'",
            41031: "41031:'Inside U.S.A. with Chevrolet'",
            41035: "41035:'Leave It to the Girls'",
            41036: "41036:'The Life of Riley'",
            41037: "41037:'Lights Out'",
            41038: "41038:'The Lone Ranger'",
            41039: "41039:'Mama'",
            41040: "41040:'Man Against Crime'",
            41042: "41042:'Martin Kane'",
            41044: "41044:'Mr. I. Magination'",
            41046: '41046:"The O\'Neills"',
            41048: '41048:"One Man\'s Family"',
            41049: '41049:"The Paul Whiteman\'s Goodyear Revue"',
            41050: "41050:'The Ruggles'",
            41053: "41053:'The Silver Theatre'",
            41061: "41061:'Suspense'",
            41062: "41062:'TV Teen Club'",
            41063: "41063:'That Wonderful Guy'",
            41064: "41064:'Think Fast'",
            41065: "41065:'This Is Show Business'",
            41068: "41068:'Versatile Varieties'",
            41069: "41069:'The Voice of Firestone'",
            41071: "41071:'Wayne King'",
            41072: '41072:"Through Wendy\'s Window"',
            41076: "41076:'Your Show Time'",
            41077: "41077:'Your Witness'",
            42069: "42069:'The Adventures of Ellery Queen'",
            42070: "42070:'The Alan Young Show'",
            42072: "42072:'American Forum of the Air'",
            42074: "42074:'Armstrong Circle Theatre'",
            42078: "42078:'The Arthur Murray Party'",
            42079: "42079:'Battle Report'",
            42080: "42080:'Beat the Clock'",
            42081: "42081:'Beulah'",
            42082: "42082:'Big Top'",
            42083: "42083:'Big Town'",
            42084: "42084:'The Bigelow Theatre'",
            42086: "42086:'The Billy Rose Show'",
            42089: "42089:'Cavalcade of Bands'",
            42091: "42091:'Chance of a Lifetime'",
            42092: "42092:'Charlie Wild, Private Detective'",
            42093: "42093:'The Cisco Kid'",
            42094: "42094:'The Colgate Comedy Hour'",
            42095: "42095:'The College Bowl'",
            42097: "42097:'Crusader Rabbit'",
            42098: "42098:'Danger'",
        },
    }
