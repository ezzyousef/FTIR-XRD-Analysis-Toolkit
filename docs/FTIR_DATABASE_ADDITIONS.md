# FTIR database v4.3 — added materials and their evidence

Thirteen materials common in energy-materials work were added on 2026-10-07. Every band below is
traced to a quoted excerpt of a published or institutional source found by literature/web
search (Consensus and web search). **The full texts were not opened** — NIST WebBook, PubMed
Central and publisher sites were blocked by the build environment's network policy — so every
entry carries `"provenance": {"verify": true, "confidence": ...}`. Check the values against the
original papers or a reference spectrum (NIST WebBook, SDBS) before using a match in a report.

Confidence: **medium** = several independent sources agree on the band positions;
**low** = some bands rest on a single or educational source.

| Material | Category | Bands (cm⁻¹) | Evidence (quoted values) | Confidence |
|---|---|---|---|---|
| Water (liquid H₂O) | organics | O–H 3150–3550; bend 1630–1650; combination 2100–2150; libration 450–800 | OH stretching band "between 3150 and 3550" (Carpenter 2017); bend "v2, 1644" (Univ. Sydney teaching text); bend+libration band "centered at 2130" (Verma 2017; Chieffo 2007); libration near 500 and 435/600/770 Raman components (Xu 2019 and cited work); reference optical constants: Bertie & Lan 1996 | medium |
| Ethanol | organics | O–H 3200–3500; C–H 2850–2980; C–O 1045–1060 and 1085–1105 | neat alcohols O–H "3500-3200"; ethanol "O–H stretch (3391) and the C–O stretches (1102, 1055)" (U. Colorado Boulder IR tutorial); C–H: general alkyl correlation (Socrates; Pavia) | medium |
| Acetone | organics | C=O 1705–1720; CH₃ def. 1355–1370; C–C–C 1215–1230 | C=O "1715 cm-1 region" (Cha 1999, PCCP); 1365 CH bend and 1225 C–C stretch (educational web guide); full assignment: Dellepiane & Overend 1966 (abstract only) | low |
| DMSO | organics | S=O 1040–1060; 940–955; 1300–1315; 1398–1410; 1430–1442 | IR "947 and 1,054 cm-1 (S-O stretching coupled with CH3 rocking)", "CH3 umbrella 1,307", "CH3 bending 1,403 and 1,436" (SI of arXiv:1904.02857); S=O 1057 in ethylene glycol solution | medium |
| Ethylene carbonate | organics | C=O 1770–1780 and 1798–1808; ring breathing 888–900; C=O bend 714–722 | pure EC "doublet observed at 1774 and 1803", "ring breathing … 893", "C=O bending band from 718" (FTIR study of EC + LiCF₃SO₃, U. Malaya repository); free-EC ring breathing 896 | medium |
| Dimethyl carbonate | organics | C=O 1745–1770; O–C–O 1240–1280; 965–975 | C=O "around 1750" (patent) and free C=O "1767" (LiPF₆/DMC 2D-IR, RSC SI); saturated carbonates "O-C-O peak from 1280 to 1240" (Spectroscopy, polymer IR series); solid DMC feature "near 971" (Hudson 2019) | low |
| Graphene oxide | elements | O–H 3200–3600; C=O 1720–1740; C=C/H₂O 1600–1630; epoxy 1220–1240; alkoxy 1040–1075 | "peak at around 3400 … OH"; "1735 … C=O" (two studies); "1625 … adsorbed water … and skeletal vibrations of unoxidized graphitic domains"; "1230 … C-O-C epoxide"; "1050 … C-O" / "1075 … alkoxy" | medium |
| Reduced graphene oxide | elements | C=C 1560–1580; residual C=O 1720–1740; C–O 1180–1240; 1040–1080 | "band at 1570 … C=C bonds of rGO"; "intensity of the 1724 cm-1 band (C=O) greatly decreases"; residual epoxy/alkoxy C–O bands | low |
| Oxidized MWCNT | elements | O–H 3400–3450; C=O 1700–1740; C=C 1560–1600; C–O–C 1225–1261; C–O 1044–1056 | "3428 … O—H stretch from carboxyl groups"; "1719 … C=O stretching"; "1572 … C═C … backbone of MWCNT"; "C–O stretching near 1044–1056"; "C–O–C/epoxide near 1225–1261" | medium |
| CMC (Na salt) | polymers | O–H 3200–3500; COO⁻ as 1590–1615; COO⁻ s 1410–1425 and 1320–1330; C–O 1105–1115, 1050–1060, 1020–1030; glycosidic 890–900 | "asCOO- at 1650 and 1592 … sCOO- at 1416 and 1324"; "C2-OH at 1112, C3-OH at 1056, C6-OH at 1025"; glycosidic "896"; carboxylate "1613 and 1602", "1420" | medium |
| Nafion | polymers | CF₂ 1200–1225 and 1145–1155; SO₃⁻ 1050–1064; C–O–C 980–985; 965–972 | "very strong bands at 1200 and 1148 … CF2"; "1220 … vas(CF2) and vas(SO3-)"; sulfonate "1064" / "1050" / "1061"; ether "983"; "970" feature (assignment disputed, J. Mater. Chem. A correction 2024) | medium |
| LiPF₆ | salts | P–F 826–845; F–P–F 555–570 | "P–F stretch at 826"; "around 845"; free/ion-paired PF₆⁻ "843 / 834"; "T1u infrared mode is observed at 567"; LiPF₆ band "at 559" | medium |
| LiFePO₄ | minerals | ν₃ 1000–1200; ν₁ 955–972; ν₄ 590–640 | "intense broad MIR bands … between 1000–1200 … antisymmetric P–O stretching ν3"; ν₁ "from 970 to 957" (F-doped LiFePO₄); "593–637 … O–P–O bending" (Raman/DFT) | medium |

**Not added:** N-methyl-2-pyrrolidone (NMP). The only band found with a source was its C=O at
1670 cm⁻¹ *hydrogen-bonded to polyaniline*, which does not describe the neat solvent. Add NMP
from a NIST WebBook or SDBS reference spectrum once those sites are reachable.

**How the matcher sees them (simulated spectra, `tools/benchmark_ftir_matching.py` method):**
CMC, Nafion, acetone, DMSO, EC, DMC, GO, rGO and oxidized MWCNT are found first, mostly rated
Strong. LiPF₆ is found first but rated Poor (two bands only). Water and LiFePO₄ — almost all
broad bands — are hard to identify from a peak list; compare their spectra directly.

**To improve these entries:** allow `webbook.nist.gov`, `sdbs.db.aist.go.jp` and
`pmc.ncbi.nlm.nih.gov` in the environment's network settings so band positions can be read
from reference spectra and full texts, then remove `verify` from entries that check out.
