# Pipeline de la fábrica

```mermaid
flowchart LR
  s0["architect<br/>190 s"]:::ok
  s1["architect<br/>235 s"]:::ok
  s2["qa-unit<br/>298 s"]:::ok
  s3["verify unit<br/>5 s"]:::fail
  s4["deploy<br/>27 s"]:::ok
  s5["qa-e2e<br/>86 s"]:::ok
  s6["developer<br/>98 s"]:::ok
  s7["security<br/>320 s"]:::ok
  s8["architect<br/>382 s"]:::ok
  s9["verify unit<br/>4 s"]:::ok
  s10["verify contract<br/>5 s"]:::ok
  s11["verify qa<br/>9 s"]:::fail
  s12["qa-unit<br/>28 s"]:::ok
  s13["verify unit<br/>4 s"]:::ok
  s14["verify contract<br/>5 s"]:::ok
  s15["verify qa<br/>9 s"]:::ok
  s16["verify e2e<br/>4 s"]:::ok
  s17["verify evaluate<br/>3 s"]:::ok
  s18["qa-style<br/>92 s"]:::ok
  s19["verify production<br/>1750 s"]:::fail
  s0 --> s1
  s1 --> s2
  s2 --> s3
  s3 --> s4
  s3 --> s5
  s3 --> s6
  s3 --> s7
  s4 --> s8
  s5 --> s8
  s6 --> s8
  s7 --> s8
  s8 --> s9
  s9 --> s10
  s10 --> s11
  s11 --> s12
  s12 --> s13
  s13 --> s14
  s14 --> s15
  s15 --> s16
  s16 --> s17
  s17 --> s18
  s18 --> s19
  classDef ok fill:#d4f4dd,stroke:#1e7b3a
  classDef fail fill:#fde2e2,stroke:#a12a2a
```

| # | Paso | Resultado | Segundos |
| --- | --- | --- | --- |
| 1 | architect | pasó | 190 |
| 2 | architect | pasó | 235 |
| 3 | qa-unit | pasó | 298 |
| 4 | verify unit | falló | 5 |
| 5 | deploy | pasó | 27 |
| 6 | qa-e2e | pasó | 86 |
| 7 | developer | pasó | 98 |
| 8 | security | pasó | 320 |
| 9 | architect | pasó | 382 |
| 10 | verify unit | pasó | 4 |
| 11 | verify contract | pasó | 5 |
| 12 | verify qa | falló | 9 |
| 13 | qa-unit | pasó | 28 |
| 14 | verify unit | pasó | 4 |
| 15 | verify contract | pasó | 5 |
| 16 | verify qa | pasó | 9 |
| 17 | verify e2e | pasó | 4 |
| 18 | verify evaluate | pasó | 3 |
| 19 | qa-style | pasó | 92 |
| 20 | verify production | falló | 1750 |
