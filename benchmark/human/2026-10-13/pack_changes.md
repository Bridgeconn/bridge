# ta-irv round 3 (2026-10-13): what the reviewer's verdicts say

Converter output; numbers are the reviewer's verdicts on this round only. The benchmark
(`scripts/language_qa_benchmark.py --human-labels benchmark/human`) is the score of record.

| rule | kind | labelled | TP | FP | house | precision |
|---|---|---|---|---|---|---|
| `common/punctuation.repeated` | flagged | 1 | 1 | 0 | 0 | 100% |
| `common/spacing.extra` | flagged | 15 | 8 | 7 | 0 | 53% |
| `common/unicode.invisible` | flagged | 1 | 1 | 0 | 0 | 100% |
| `heading.marker-inconsistent` | candidate | 4 | 4 | 0 | 0 | 100% |
| `heading.trailing-punctuation` | candidate | 25 | 25 | 0 | 0 | 100% |
| `ta-irv/indicqa.lex.compound` | flagged | 25 | 12 | 13 | 0 | 48% |
| `ta-irv/indicqa.lex.near-miss` | flagged | 40 | 10 | 30 | 0 | 25% |
| `ta-irv/indicqa.lex.unknown` | flagged | 25 | 3 | 22 | 0 | 12% |
| `ta-irv/indicqa.punct.no-space-after` | flagged | 1 | 1 | 0 | 0 | 100% |
| `ta-irv/indicqa.punct.repeated` | flagged | 2 | 1 | 1 | 0 | 50% |
| `ta-irv/indicqa.sandhi.conflict` | flagged | 20 | 16 | 4 | 0 | 80% |
| `ta-irv/indicqa.sandhi.dangling` | flagged | 7 | 6 | 1 | 0 | 86% |
| `ta-irv/indicqa.sandhi.extra` | flagged | 50 | 10 | 33 | 7 | 23% |
| `ta-irv/indicqa.sandhi.missing` | flagged | 30 | 25 | 1 | 4 | 96% |
| `ta-irv/indicqa.sandhi.wrong-class` | flagged | 1 | 0 | 1 | 0 | 0% |
| `ta-irv/indicqa.shape.initial-pulli` | flagged | 4 | 3 | 1 | 0 | 75% |
| `ta-irv/indicqa.shape.malformed` | flagged | 9 | 9 | 0 | 0 | 100% |
| `ta-irv/indicqa.shape.unusual-initial` | flagged | 8 | 0 | 8 | 0 | 0% |
| `ta-irv/lexicon.known-misspelling` | flagged | 30 | 23 | 7 | 0 | 77% |
| `ta-irv/sandhi.compound.direction` | flagged | 15 | 15 | 0 | 0 | 100% |
| `ta-irv/sandhi.vallinam.demonstrative` | flagged | 20 | 20 | 0 | 0 | 100% |
| `ta-irv/sandhi.vallinam.manner-adverb` | flagged | 1 | 1 | 0 | 0 | 100% |
| `ta-irv/typo.divine-name.dative-stem` | flagged | 9 | 9 | 0 | 0 | 100% |
| `ta-irv/typo.divine-name.vowel-drop` | flagged | 6 | 6 | 0 | 0 | 100% |
| `ta-irv/typo.participle.sentence-final` | flagged | 1 | 1 | 0 | 0 | 100% |
| `usfm.footnote-no-text` | candidate | 3 | 3 | 0 | 0 | 100% |
| `usfm.ior-trailing-space` | candidate | 3 | 3 | 0 | 0 | 100% |
| `usfm.note-caller` | candidate | 2 | 2 | 0 | 0 | 100% |
| `usfm.wj-boundary` | candidate | 2 | 2 | 0 | 0 | 100% |
| `usfm.wj-outside-gospels` | candidate | 1 | 1 | 0 | 0 | 100% |

## Word list (sheet 3)

15 rows; 39 new one-word pairs written to `lexicon_curated.csv` (word list and confirmed sheet-2 pairs).

- தண்ணீனால் → தண்ணீரினால்: already in the shipped map (→ தண்ணீரினால்); dropped
- உடன்பட்டிக்கை → உடன்படிக்கை: already in the shipped map (→ உடன்படிக்கை); dropped
- எல்லாக்கூட்டத்தாரும் → எல்லாக் கூட்டத்தாரும்: joined words, a known-join candidate (item 4)
- போர்செய்யப்புறப்பட்டு → போர்செய்யப் புறப்பட்டு: joined words, a known-join candidate (item 4)
- நகரத்தைப்பிடிக்கும்படி → நகரத்தைப் பிடிக்கும்படி: joined words, a known-join candidate (item 4)
- சொல்லுகிறேன்என்றார் → சொல்லுகிறேன் என்றார்: joined words, a known-join candidate (item 4)
- இல்லையா?என்றார் → இல்லையா? என்றார்: joined words, a known-join candidate (item 4)
- அடைந்தனஎன்றார் → அடைந்தன என்றார்: joined words, a known-join candidate (item 4)
- வைத்தீர்கள்?என்றார் → வைத்தீர்கள்? என்றார்: joined words, a known-join candidate (item 4)
- இருதயத்தார்கள் → இருதயத்தார்: already shipped as a human pair (ta-irv/indicqa.lex.near-miss); dropped
- எவ்விடத்திற்குப்போக → எவ்விடத்திற்குப் போக: not one word for one word (ta-irv/indicqa.lex.unknown); the lexicon builder drops it
- தெற்குதிசைக்கு → தெற்குத் திசைக்கு: not one word for one word (ta-irv/lexicon.known-misspelling); the lexicon builder drops it

## Reviewer notes on false alarms

- `ta-irv/indicqa.sandhi.missing` EXO 16:5 «இரண்டுமடங்கு»: "மடங்கு" இங்கு அளவு வினையடை; மிகல் தேவையில்லை. உண்மையான திருத்தம் இடைவெளி: இரண்டு மடங்கு சேர்த்து.
- `ta-irv/indicqa.sandhi.wrong-class` GEN 4:18 «ஈராத்»: ஈராத் = ஆட்பெயர் (Irad); த் பெயரின் பகுதி, ஒற்று அல்ல. பெயர்ப் பட்டியலில் சேர்க்கவும்.
- `ta-irv/indicqa.sandhi.conflict` EXO 30:25 «அபிஷேகத்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.conflict` EXO 39:38 «அபிஷேகத்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.conflict` JHN 6:1 «கலிலேயாக்»: கலிலேயாக் கடல் — அதே வசனத்தில் "திபேரியாக் கடல்". 1A-வில் இதற்கு எதிர் விதி "கலிலேயாக்" வேண்டும் என்கிறது; இரண்டு விதிகளும் முரண்.
- `ta-irv/indicqa.sandhi.conflict` LEV 8:30 «அபிஷேகத்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.dangling` EZK 27:17 «மின்னித்»: மின்னித் = ஊர்ப்பெயர் (Minnith); த் பெயரின் பகுதி. பெயர்ப் பட்டியலில் சேர்க்கவும்.
- `ta-irv/indicqa.sandhi.extra` 1CH 21:12 «மூன்றுமாதத்»: மாதம் → மாதத் (அம் கெட்டு மிகும்), "மூன்று வருடத்துப் பஞ்சம்" போல. இடைவெளி மட்டும் சேர்க்கவும்.
- `ta-irv/indicqa.sandhi.extra` 1KI 20:11 «பெருமைபாராட்டக்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை. இடைவெளி சேர்க்கவும்.
- `ta-irv/indicqa.sandhi.extra` 1PE 2:9 «ஆசாரியக்»: ஆசாரியக் கூட்டம் — பெயர் + பெயர் தொகை; OV/IRV வழக்கும் இதுவே.
- `ta-irv/indicqa.sandhi.extra` 2CO 3:1 «சிபாரிசுக்»: அதே வசனத்தில் "சிபாரிசுக் கடிதங்களை" ஏற்கனவே மிகலுடன்; பெயர்த்தொகை.
- `ta-irv/indicqa.sandhi.extra` 2KI 6:6 «மிதக்கச்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.sandhi.extra` 2KI 12:16 «குற்றப்பிராயசித்தப்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.extra` ACT 4:12 «மரபுத்»: "மரபுத்தொடர்" (idiom) — நிலைத்த சொல்.
- `ta-irv/indicqa.sandhi.extra` ACT 8:8 «சமாரியாப்»: சமாரியாப் பட்டணம் — கலிலேயாக் கடல் போல.
- `ta-irv/indicqa.sandhi.extra` ACT 21:28 «இந்தத்»: அந்த/இந்த + வல்லினம் எப்போதும் மிகும். இது கடுமையான தவறான எச்சரிக்கை — சுட்டு விதி மிகலைக் கேட்கிறது, sandhi.extra நீக்கச் சொல்கிறது.
- `ta-irv/indicqa.sandhi.extra` AMO 6:4 «தந்தக்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல). (தந்தம் → தந்தக் கட்டில்)
- `ta-irv/indicqa.sandhi.extra` DAN 6:22 «சேதப்படுத்தாதபடிக்குத்»: -படிக்கு (4-ஆம் வேற்றுமை) + வல்லினம் மிகும்.
- `ta-irv/indicqa.sandhi.extra` DEU 5:20 «பொய்ச்»: ய் ஈறு + வல்லினம் மிகும் (பொய்ச்சாட்சி).
- `ta-irv/indicqa.sandhi.extra` DEU 23:25 «பயன்படுத்தக்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.sandhi.extra` EZK 39:26 «பரிசுத்தப்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல). (பரிசுத்தம் → பரிசுத்தப் பெயர்)
- `ta-irv/indicqa.sandhi.extra` EZK 43:7 «பரிசுத்தப்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.extra` EZK 43:8 «பரிசுத்தப்»: அம் ஈற்றுப் பெயர் புணர்ச்சியில் அம் கெட்டு வல்லினம் மிகும் (மரக்கிளை போல).
- `ta-irv/indicqa.sandhi.extra` ISA 42:10 «புதுப்»: புது + வல்லினம் மிகும் (புதுக்கவிதை).
- `ta-irv/indicqa.sandhi.extra` JHN 19:19 «பொருத்தச்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.sandhi.extra` JOS 1:11 «உணவுப்»: உணவுப் பொருள் — நிலைத்த வடிவம்.
- `ta-irv/indicqa.sandhi.extra` LUK 9:12 «உணவுப்»: உணவுப் பொருள் — நிலைத்த வடிவம்.
- `ta-irv/indicqa.sandhi.extra` LUK 9:17 «உணவுப்»: உணவுப் பொருள் — நிலைத்த வடிவம்.
- `ta-irv/indicqa.sandhi.extra` LUK 13:19 «கடுகுச்»: கடுகுச் செடி — பெயர்த்தொகை.
- `ta-irv/indicqa.sandhi.extra` LUK 23:2 «குற்றஞ்சுமத்தத்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.sandhi.extra` MAT 3:11 «சுமக்கிறதற்குக்»: 4-ஆம் வேற்றுமை + கூட (அதற்குக் கூட) — மிகும்.
- `ta-irv/indicqa.sandhi.extra` MAT 6:1 «நீதிச்»: இ ஈற்றுப் பெயர்த்தொகை (நீதிச் செயல்) — மிகும்.
- `ta-irv/indicqa.sandhi.extra` MAT 21:9 «எழுத்துப்»: "எழுத்துப்பெயர்ப்பு" (transliteration) — நிலைத்த சொல்.
- `ta-irv/indicqa.sandhi.extra` NEH 8:15 «மிருதுச்»: மிருதுச் செடி (OV வழக்கு); பெயர்த்தொகை. அதே வசனத்தில் "எல்லா பட்டணங்களிலும்" மிகல் விடுபட்டது.
- `ta-irv/indicqa.sandhi.extra` PSA 29:6 «துள்ளச்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.sandhi.extra` PSA 60:2 «பொருந்தச்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை. (படிக்கவும் தாளின் எடுத்துக்காட்டு இதுவே.)
- `ta-irv/indicqa.sandhi.extra` PSA 96:1 «புதுப்»: புது + வல்லினம் மிகும்.
- `ta-irv/indicqa.sandhi.extra` PSA 145:5 «மகிமைப்»: மகிமைப் பிரதாபம் — ஐ ஈற்றுப் பெயர்த்தொகை, மிகும்.
- `ta-irv/indicqa.sandhi.extra` ROM 9:29 «வம்சத்தைக்»: 2-ஆம் வேற்றுமை ஐ + கூட — மிகும் (ஒன்றைக்கூட). "வம்சத்தைக்கூட" என்று சேர்த்தும் எழுதலாம்.
- `ta-irv/indicqa.sandhi.extra` ROM 10:3 «நிலைநிறுத்தத்»: செய என் எச்சம் (-க/-ச்ச/-த்த) + வல்லினம் → மிகும் (செய்யக் கூடாது, பொருந்தச் செய்). sandhi.extra இந்த வகையில் தவறாகத் தூண்டுகிறது — முறையான பிழை.
- `ta-irv/indicqa.lex.compound` 2CH 25:8 «விழச்செய்யவும்»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல.
- `ta-irv/indicqa.lex.compound` ACT 27:12 «மழைக்காலத்தில்»: மழைக்காலம் = ஒரே சொல்; அதே வசனத்தில் "மழைக்காலத்திலே".
- `ta-irv/indicqa.lex.compound` GAL 2:14 «நடந்துகொண்டிருக்க»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல.
- `ta-irv/indicqa.lex.compound` GEN 29:9 «மேய்த்துக்கொண்டிருந்த»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல.
- `ta-irv/indicqa.lex.compound` JHN 14:19 «பார்க்காது»: பார்க்காது = ஒரே வினைச்சொல் (எதிர்மறை). "பார்க் காது" பொருளற்றது — பிரித்தல் விதி -ாது முடிவை விலக்க வேண்டும்.
- `ta-irv/indicqa.lex.compound` JOB 35:15 «தண்டிக்கவில்லை»: தண்டிக்கவில்லை = ஒரே சொல்; -இல்லை எதிர்மறையை விலக்கவும்.
- `ta-irv/indicqa.lex.compound` LEV 21:5 «சிரைத்துக்கொள்ளாமலும்»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல. அதே வசனத்தில் "கீறிக்கொள்ளாமலும்".
- `ta-irv/indicqa.lex.compound` MAT 12:6 «வழிபாட்டு»: வழிபாடு = ஒரே சொல். பிரித்தால் பொருளற்றது — இது ஒரே சொல்.
- `ta-irv/indicqa.lex.compound` NEH 8:3 «திறந்தவெளிக்கு»: திறந்தவெளி — நிலைத்த கூட்டுச்சொல்.
- `ta-irv/indicqa.lex.compound` NUM 31:2 «பழிவாங்கு»: பழிவாங்கு — நிலைத்த கூட்டுவினை.
- `ta-irv/indicqa.lex.compound` PSA 22:9 «இருக்கச்செய்தீர்»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல.
- `ta-irv/indicqa.lex.compound` REV 22:15 «மாசுபட்ட»: மாசுபட்ட — நிலைத்த கூட்டுச்சொல் (கறைபட்ட போல).
- `ta-irv/indicqa.lex.compound` RUT 3:4 «படுத்துக்கொண்ட»: துணைவினை/காரணவினை சேர்த்து எழுதுவது இக்கால நடையில் ஏற்கத்தக்கது; IRV இரண்டு வழக்கையும் பயன்படுத்துகிறது. பிழை அல்ல. அதே வசனத்தில் "படுத்துக்கொள்".
- `ta-irv/indicqa.lex.near-miss` 1CO 7:36 «பருவம்»: கன்னிப் பருவம் — சரியான சொல்.
- `ta-irv/indicqa.lex.near-miss` 1SA 1:18 «சாப்பிட்டாள்»: அவள் சாப்பிட்டாள் — சரி.
- `ta-irv/indicqa.lex.near-miss` 2CH 8:11 «குடிவரச்»: குடிவரச் செய்தான் = குடியமர்த்தினான்; சரி.
- `ta-irv/indicqa.lex.near-miss` 2CH 22:10 «கொன்றுபோட்டாள்»: அத்தாலியாள் (பெண்) — கொன்றுபோட்டாள் சரி.
- `ta-irv/indicqa.lex.near-miss` 2KI 5:10 «எழு»: மூழ்கி எழு (எழுந்திரு) — சரி.
- `ta-irv/indicqa.lex.near-miss` 2KI 20:11 «கோடு»: "கோட்டுக்குக் கோடு" (மிகல் விடுபட்டது), "பத்துகோடுகள்" → பத்துக் கோடுகள் — இவை தனிப் பிழைகள்.
- `ta-irv/indicqa.lex.near-miss` 2KI 23:10 «பென்»: பென் இன்னோம் (Ben-Hinnom) — இடப்பெயர்.
- `ta-irv/indicqa.lex.near-miss` DAN 4:22 «ராஜரீகம்»: ராஜரீகம் — OV/IRV வழக்கு.
- `ta-irv/indicqa.lex.near-miss` GEN 36:11 «எலிப்பாசின்»: எலிப்பாஸ் — OV வழக்கு (யோபு நண்பனும் எலிப்பாஸ்).
- `ta-irv/indicqa.lex.near-miss` ISA 11:9 «நிறைந்திருக்கிறதுபோல»: போல/போல் இரண்டும் சரி. அதே வசனத்தில் "தண்ணீனால்" → தண்ணீரினால் (தாள் 3-இல் சேர்த்தேன்).
- `ta-irv/indicqa.lex.near-miss` ISA 38:21 «பழத்து»: அத்திப் பழத்து அடை — சரி.
- `ta-irv/indicqa.lex.near-miss` JDG 19:18 «தொலை»: தொலை தூரம் — சரி.
- `ta-irv/indicqa.lex.near-miss` JOB 15:11 «மென்மையான»: மென்மையான பேச்சு — பொருள் சரி.
- `ta-irv/indicqa.lex.near-miss` JOS 15:32 «ஆயீன்»: ஆயீன் — ஊர்ப்பெயர் (Ain).
- `ta-irv/indicqa.lex.near-miss` JOS 15:61 «அரபா»: பெத் அரபா — ஊர்ப்பெயர்.
- `ta-irv/indicqa.lex.near-miss` MAT 22:13 «காலையும்»: கை கால் — சரி.
- `ta-irv/indicqa.lex.near-miss` NUM 4:6 «நீலமான»: நீலமான துப்பட்டி — சரி.
- `ta-irv/indicqa.lex.near-miss` PSA 119:8 «பேத்»: பேத் = எபிரெய எழுத்தின் பெயர் (சங் 119 பத்தித் தலைப்பு). ஆனால் வசனம் 8-இன் உரையில் ஒட்டியுள்ளது — \qa தலைப்பாக இருக்க வேண்டும் (அமைப்புப் பிழை).
- `ta-irv/indicqa.lex.near-miss` ZEC 14:10 «ஆலைகள்»: திராட்சை ஆலைகள் = ஆலை (winepress); சரி.
- `ta-irv/indicqa.lex.unknown` 1CO 15:5 «கேபாவிற்கும்»: கேபா (Cephas).
- `ta-irv/indicqa.lex.unknown` 1SA 6:19 «கொன்றார்»: சொல் சரி; ஆனால் "பேர்களைக் கொன்றார்" — மிகல் விடுபட்டது.
- `ta-irv/indicqa.lex.unknown` JOS 21:33 «கெர்சோனியர்களுக்கு»: கெர்சோனியர் (Gershonites).
- `ta-irv/indicqa.lex.unknown` LUK 22:3 «ஸ்காரியோத்»: ஸ்காரியோத் — பெயர்.
- `ta-irv/indicqa.lex.unknown` MRK 2:19 «இருப்பார்களா»: வினாச்சொல் — சரி.
- `ta-irv/indicqa.lex.unknown` SNG 5:13 «கந்தவர்க்கப்»: OV உன் 5:13 "கந்தவர்க்கப் பாத்திகள்".
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:4 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி.
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:4 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி.
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:7 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி. அதே வசனத்தில் "பதிணெட்டாயிரம்" → பதினெட்டாயிரம்.
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:7 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி. அதே வசனத்தில் "பதிணெட்டாயிரம்" → பதினெட்டாயிரம்.
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:7 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி. அதே வசனத்தில் "பதிணெட்டாயிரம்" → பதினெட்டாயிரம்.
- `ta-irv/indicqa.shape.unusual-initial` 1CH 29:7 «டன்»: டன் (ton) — பிறமொழி அளவுச்சொல்; சரி. அதே வசனத்தில் "பதிணெட்டாயிரம்" → பதினெட்டாயிரம்.
- `ta-irv/indicqa.shape.unusual-initial` NEH 1:1 «டிசம்பர்»: டிசம்பர் — பிறமொழிச் சொல்; சரி. அடிக்குறிப்பில் "சூசன்" → உரையுடன் ஒத்துப்போக "சூசான்".
- `ta-irv/indicqa.shape.unusual-initial` PSA 119:24 «டாலெத்»: டாலெத் = எபிரெய எழுத்தின் பெயர்; ஆனால் வசன உரையில் ஒட்டியுள்ளது — \qa தலைப்பாக இருக்க வேண்டும்.
- `ta-irv/lexicon.known-misspelling` 1KI 1:17 «எஜமானே»: "எஜமானே" சரியான விளி. உண்மையான பிழை: அதே வசனத்தில் "உன்னுடைய மகனாகிய" → "உம்முடைய" (மற்ற இடங்களில் உம்/நீர்).
- `ta-irv/lexicon.known-misspelling` 1KI 4:5 «ஆளுநர்களின்»: ஆளுநர்களின் தலைவன் — சரி; பரிந்துரை பொருளை மாற்றும்.
- `ta-irv/lexicon.known-misspelling` 1KI 22:34 «ரத»: IRV முழுவதும் "ரதம்" வழக்கு.
- `ta-irv/lexicon.known-misspelling` 1SA 19:20 «சவுலினுடைய»: சவுலினுடைய / சவுலுடைய இரண்டும் சரி (இன் சாரியை).
- `ta-irv/lexicon.known-misspelling` EXO 38:3 «கிண்ணிகளையும்»: கிண்ணி = சிறு கிண்ணம்; சரியான சொல்.
- `ta-irv/lexicon.known-misspelling` LEV 13:35 «தீர்க்கப்பட்ட»: "தீர்க்கப்பட்ட" — OV வழக்கு, சரி; பரிந்துரை நடை மாற்றம்.
- `ta-irv/lexicon.known-misspelling` MRK 6:20 «யோசனையின்படி»: யோசனை = ஆலோசனை; சரி. பரிந்துரை நடை மாற்றம்.
- `common/spacing.extra` MAT 16:8 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` MAT 16:9 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` MAT 16:17 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` MAT 16:26 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` PSA 68:32 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` PSA 84:8 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `common/spacing.extra` REV 3:6 « »: வசன இறுதியில் உள்ள இடைவெளி USFM-இல் பொருளற்றது (அடுத்த \v-க்கு முன் இயல்பு); குறிக்க வேண்டாம்.
- `ta-irv/indicqa.punct.repeated` LUK 2:44 «.,»: சுருக்கக் குறிப் புள்ளி + காற்புள்ளி (கி.மீ.,) — சரியானது.
- `ta-irv/indicqa.shape.initial-pulli` PSA 119:136 «த்சாடே»: த்சாடே = எபிரெய எழுத்தின் பெயர் (OV "சாதே"); பிழை அல்ல. ஆனால் வசன உரையில் உள்ளது — \qa தலைப்பாக இருக்க வேண்டும்.
