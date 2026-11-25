"""Mechanical rows for spellings that the whole Bible overwhelmingly writes another way.
Each entry: (regex for the flagged word, function word->corrected word, issue type, severity, confidence, reason, (count-pattern-wrong, count-pattern-right))
build.py adds one row per occurrence (first occurrence of each form per verse) unless the rows file sets NO_MINORITY=True."""
import re
T="ఀ-౿‌"
W=lambda core: rf"[{T}]*{core}[{T}]*"
def sub(a,b): return lambda w: re.sub(a,b,w)
FORMS=[
 (W("ళ్ల"),sub("ళ్ల","ళ్ళ"),"Possible typo","Low","Medium","The double ళ is written ళ్ళ in this edition; ళ్ల is the minority spelling.",("ళ్ల","ళ్ళ")),
 (rf"[{T}]+కొనే(?![{T}])",sub("కొనే$","కునే"),"Possible typo","Low","Medium","The reflexive participle is normally -కునే in this edition; -కొనే is the older minority form.",(rf"కొనే(?![{T}])",rf"కునే(?![{T}])")),
 (rf"(?<![{T}])తరవాత[{T}]*",sub("తరవాత","తరువాత"),"Possible typo","Low","Medium","The edition normally writes తరువాత.",("తరవాత","తరువాత")),
 (rf"(?<![{T}])[ఎఅఇ]లాటి[{T}]*",sub("లాటి","లాంటి"),"Possible typo","Low","Medium","The edition normally writes -లాంటి with the anusvara.",("[ఎఅఇ]లాటి","[ఎఅఇ]లాంటి")),
 (rf"(?<![{T}])దగ్గరక[ుే](?![{T}])",lambda w:w.replace("దగ్గరకు","దగ్గరికి").replace("దగ్గరకే","దగ్గరికే"),"Possible typo","Medium","High","The directional form is దగ్గరికి in this edition; దగ్గరకు / దగ్గరకే is rare.",("దగ్గరక[ుే]","దగ్గరిక[ిే]")),
 (W("బ్రతిమా"),sub("బ్రతిమా","బతిమా"),"Possible typo","Low","Medium","The verb is బతిమాలు in this edition; the బ్ర- form is rare.",("బ్రతిమా","బతిమా")),
 (rf"(?<![{T}])బ్రత[ుిక][{T}]*",sub("బ్రత","బత"),"Possible typo","Low","Medium","The edition normally writes బతుకు / బతికి without ర; the బ్ర- form is the minority.",(rf"(?<![{T}])బ్రత[ుిక]",rf"(?<![{T}])బత[ుిక]")),
 (rf"(?<![{T}])కూడ(?![{T}])",sub("కూడ$","కూడా"),"Possible typo","Medium","High","కూడా is written with the long vowel in this edition; the short form is rare.",(rf"(?<![{T}])కూడ(?![{T}])",rf"(?<![{T}])కూడా(?![{T}])")),
 (rf"[{T}]+టానికి[{T}]*",sub("టానికి","డానికి"),"Possible typo","Low","Medium","The purposive ending is -డానికి in this edition; -టానికి is rare.",("టానికి","డానికి")),
 (rf"(?<![{T}])చూ[సచ]ా[{T}]*",sub("చూ[సచ]ా","చూశా"),"Confirmed typo","Medium","High","The past tense of చూచు is written with శ in this edition (చూశా-).",("చూ[సచ]ా","చూశా")),
 (rf"[{T}]+న్నపుడు[{T}]*",sub("న్నపుడు","న్నప్పుడు"),"Possible typo","Low","High","The edition writes -న్నప్పుడు with doubled ప్ప.",("న్నపుడు","న్నప్పుడు")),
 (rf"[{T}]*(?<!వ)(?<!ని)(?<!ప)ర్ధ[{T}]*",sub("ర్ధ","ర్థ"),"Confirmed typo","Medium","High","Aspirate confusion: the standard spelling of this word has థ (ర్థ), not ధ.",None),
 (rf"(?<![{T}])యధార్[థధ][{T}]*",sub("యధార్[థధ]","యథార్థ"),"Confirmed typo","Medium","High","The standard spelling is యథార్థ with థ in both places.",("యధార్","యథార్థ")),
 (rf"(?<![{T}])వృధా[{T}]*",sub("వృధా","వృథా"),"Confirmed typo","Medium","High","The standard spelling is వృథా with థ.",("వృధా","వృథా")),
 (rf"(?<![{T}])సాక్షం[{T}]*|(?<![{T}])సాక్షమి[{T}]*",lambda w:w.replace("సాక్షం","సాక్ష్యం").replace("సాక్షమి","సాక్ష్యమి"),"Confirmed typo","Medium","High","The word has lost its య-ఒత్తు; the edition writes సాక్ష్యం.",("సాక్ష(ం|మి)","సాక్ష్య(ం|మి)")),
 (rf"(?<![{T}])నిర్లక్ష(?!్య)[{T}]*",sub("నిర్లక్ష","నిర్లక్ష్య"),"Confirmed typo","Medium","High","The word has lost its య-ఒత్తు; it is నిర్లక్ష్యం.",("నిర్లక్ష(?!్య)","నిర్లక్ష్య")),
 (rf"[{T}]+(?<!లో)(?<!గా)(?<!డు)(?<!ది)(?<!కి)(?<!కు) వద్దు(?![{T}])",lambda w:w.replace(" వద్దు","వద్దు"),"Sandhi / word-joining","Low","Medium","The prohibitive వద్దు is joined to its verb in this edition (చేయవద్దు, భయపడవద్దు).",(rf"[{T}] వద్దు(?![{T}])",rf"[{T}]వద్దు(?![{T}])")),
 (rf"[{T}]+లకి(?![{T}])",sub("లకి$","లకు"),"Case/object marker","Low","Medium","The dative after a plural in -లు is -లకు in this edition; -లకి is the colloquial minority form.",(rf"[{T}]లకి(?![{T}])",rf"[{T}]లకు(?![{T}])")),
 (rf"[{T}]+(?<!ప)(?<!ప్ర)ొద్దు(?![{T}])",sub("ొద్దు$","వద్దు"),"Possible typo","Low","Medium","The prohibitive is written in full as -వద్దు in this edition; the contracted -ొద్దు is the colloquial minority form.",(rf"(?<!ప)(?<!ప్ర)ొద్దు(?![{T}])",rf"వద్దు(?![{T}])")),
 (rf"[{T}]+ినపుడు[{T}]*",sub("ినపుడు","ినప్పుడు"),"Possible typo","Low","High","The edition writes -ినప్పుడు with doubled ప్ప.",("ినపుడు","ినప్పుడు")),
 (rf"(?<![{T}])మాటలాడ[{T}]*",sub("మాటలాడ","మాట్లాడ"),"Possible typo","Low","Medium","The edition normally writes మాట్లాడు; మాటలాడు is the older minority form.",("మాటలాడ","మాట్లాడ")),
 (rf"(?<![{T}])యింట[{T}]*|(?<![{T}])యింటి[{T}]*",sub("^యిం","ఇం"),"Possible typo","Low","Medium","The edition writes ఇల్లు / ఇంట- with the independent vowel; the యి- spelling is the older minority form.",(rf"(?<![{T}])యింట",rf"(?<![{T}])ఇంట")),
 (rf"(?<![{T}])తెలుసు కో[{T}]*",sub("తెలుసు కో","తెలుసుకో"),"Sandhi / word-joining","Medium","High","తెలుసుకొను is one verb and is written as one word.",("తెలుసు కో","తెలుసుకో")),
 (rf"(?<![{T}])పాతి పెట్ట[{T}]*",sub("పాతి పెట్ట","పాతిపెట్ట"),"Sandhi / word-joining","Low","High","పాతిపెట్టు is written as one word in this edition.",("పాతి పెట్ట","పాతిపెట్ట")),
 (rf"[{T}]+కొంట[ాూు][{T}]*",sub("కొంట","కుంట"),"Possible typo","Low","Medium","The reflexive is normally -కుంట- in this edition; -కొంట- is the older minority form.",("కొంట[ాూు]","కుంట[ాూు]")),
 (rf"[{T}]+కొన్న(?![{T}])",sub("కొన్న$","కున్న"),"Possible typo","Low","Medium","The reflexive participle is normally -కున్న in this edition; -కొన్న is the older minority form.",(rf"కొన్న(?![{T}])",rf"కున్న(?![{T}])")),
 (rf"(?<![{T}])స్వంత[{T}]*",sub("స్వంత","సొంత"),"Possible typo","Low","Medium","The edition normally writes సొంత.",("స్వంత","సొంత")),
 (rf"[{T}]+ేటపుడు[{T}]*",sub("ేటపుడు","ేటప్పుడు"),"Possible typo","Low","High","The edition writes -ేటప్పుడు with doubled ప్ప.",("ేటపుడు","ేటప్పుడు")),
 (rf"(?<![{T}])దగ్గరక[ిీ](?![{T}])",lambda w:w.replace("దగ్గరకి","దగ్గరికి").replace("దగ్గరకీ","దగ్గరికీ"),"Possible typo","Low","Medium","The directional form is దగ్గరికి / దగ్గరికీ in this edition.",("దగ్గరక[ుేిీ]","దగ్గరిక[ిేీ]")),
 (rf"(?<![{T}])చూడ్డానికి[{T}]*",sub("చూడ్డానికి","చూడడానికి"),"Possible typo","Low","Medium","The contracted spoken form; the edition normally writes చూడడానికి.",("చూడ్డానికి","చూడడానికి")),
 (rf"[{T}]{{2,}}గానీ(?![{T}])",sub("గానీ$"," గానీ"),"Sandhi / word-joining","Low","Medium","The particle గానీ is written as a separate word in this edition.",(rf"[{T}]గానీ(?![{T}])",rf" గానీ(?![{T}])")),
 (rf"(?<![{T}])మనుష్యకుమారు[{T}]*",sub("మనుష్యకుమారు","మనుష్య కుమారు"),"Sandhi / word-joining","Low","High","The title is written as two words, మనుష్య కుమారుడు, in this edition.",("మనుష్యకుమారు","మనుష్య కుమారు")),
 (rf"(?<![{T}])ఆయనకి(?![{T}])",sub("ఆయనకి","ఆయనకు"),"Case/object marker","Low","High","The dative of ఆయన is ఆయనకు in this edition; -కి after a stem that does not end in ఇ is the colloquial minority form.",(rf"(?<![{T}])ఆయనకి(?![{T}])",rf"(?<![{T}])ఆయనకు(?![{T}])")),
 (rf"(?<![{T}])చెప్తున్నా[{T}]*",sub("చెప్తున్నా","చెబుతున్నా"),"Possible typo","Low","Medium","The edition normally writes చెబుతున్నా-; చెప్తున్నా- is the minority form.",("చెప్తున్నా","చెబుతున్నా")),
 (rf"(?<![{T}])బోధకుడా(?![{T}])",sub("బోధకుడా","బోధకా"),"Possible typo","Low","Medium","The vocative 'Teacher' is బోధకా in this edition; బోధకుడా is the minority form.",("బోధకుడా","బోధకా")),
 (rf"(?<![{T}])ద్రాక్షరస[{T}]*",sub("ద్రాక్షరస","ద్రాక్షారస"),"Possible typo","Low","High","The edition writes ద్రాక్షారసం with the long vowel.",("ద్రాక్షరస","ద్రాక్షారస")),
 (rf"(?<![{T}])యేసుని(?![{T}])",sub("యేసుని","యేసును"),"Case/object marker","Low","High","The object form is యేసును in this edition; -ని after a stem that does not end in ఇ is the colloquial minority form.",(rf"(?<![{T}])యేసుని(?![{T}])",rf"(?<![{T}])యేసును(?![{T}])")),
 (rf"[{T}]+డటం(?![{T}])",sub("డటం$","డడం"),"Possible typo","Low","Medium","The verbal noun is normally written -డం in this edition; -టం is the minority form.",(rf"[{T}]డటం(?![{T}])",rf"[{T}]డడం(?![{T}])")),
 (rf"(?<![{T}])ఆయన్ని(?![{T}])",sub("ఆయన్ని","ఆయనను"),"Possible typo","Low","Medium","The object form of ఆయన is ఆయనను in this edition; the contracted ఆయన్ని is the minority form.",(rf"(?<![{T}])ఆయన్ని(?![{T}])",rf"(?<![{T}])ఆయనను(?![{T}])")),
 (rf"[{T}]*డ్ద[{T}]*",sub("డ్ద","డ్డ"),"Confirmed typo","High","High","Wrong conjunct: ద is typed for డ under the డ, giving డ్ద where the word has డ్డ.",("డ్ద","డ్డ")),
 (rf"(?<![{T}])బయటకి(?![{T}])",sub("బయటకి","బయటికి"),"Possible typo","Low","Medium","The edition writes బయటికి (or బయటకు); బయటకి is the minority form.",("బయటకి","బయటికి")),
 (rf"(?<![{T}])యెముక[{T}]*",sub("^యెముక","ఎముక"),"Possible typo","Low","High","The edition writes ఎముక with the independent vowel.",(rf"(?<![{T}])యెముక",rf"(?<![{T}])ఎముక")),
 (rf"(?<![{T}])విశ్రాంతిదిన[{T}]*",sub("విశ్రాంతిదిన","విశ్రాంతి దిన"),"Sandhi / word-joining","Low","High","విశ్రాంతి దినం is written as two words in this edition.",("విశ్రాంతిదిన","విశ్రాంతి దిన")),
 (rf"(?<![{T}])ఏవిధంగా(?![{T}])",sub("ఏవిధంగా","ఏ విధంగా"),"Sandhi / word-joining","Low","High","ఏ విధంగా is written as two words in this edition.",("ఏవిధంగా","ఏ విధంగా")),
 (rf"[{T}]*చేసిక[ుొ][{T}]*",lambda w:w.replace("చేసికొ","చేసుకు").replace("చేసికు","చేసుకు"),"Possible typo","Low","Medium","The edition writes చేసుకు-; చేసికు- / చేసికొ- is the older minority form.",("చేసిక[ుొ]","చేసుకు")),
 (rf"(?<![{T}])ఐతే(?![{T}])",sub("ఐతే","అయితే"),"Possible typo","Low","High","The edition writes అయితే.",(rf"(?<![{T}])ఐతే(?![{T}])",rf"(?<![{T}])అయితే(?![{T}])")),
]
SKIP={"అలాటివారిని"} and set()
def rows_for(verses, body_end, cnt, authored):
    out=[]
    for k,t in verses.items():
        tv=t[:body_end(t)]
        for pat,fix,typ,sev,conf,why,cc in FORMS:
            m=re.search(pat,tv)
            if not m: continue
            w=m.group(0); new=fix(w)
            if cc is None:
                st=re.match(r".*?ర్ధ్?య?",w).group(0); cc=(re.escape(st),re.escape(st.replace("ర్ధ","ర్థ"))); why=why+f" Counts are for the stem {st.replace('ర్ధ','ర్థ')}-."
            cw,cr=cc
            if new==w or (k,w) in authored: continue
            nw,nr=cnt(cw)[0],cnt(cr)[0]
            if not (nr>=3*nw or typ=="Confirmed typo"): continue
            n=len(re.findall(pat,tv))
            out.append((k[0],k[1].split("-")[0],typ,"Typo" if "typo" in typ else ("Case suffix" if "Case" in typ else "Sandhi"),sev,conf,w,new,
              f"{why} Whole-Bible verse text: {nr:,} against {nw:,}."+(f" This verse has {n} such words; the first is flagged." if n>1 else ""),
              "Spelling matter; not a source question.","No"))
    return out
