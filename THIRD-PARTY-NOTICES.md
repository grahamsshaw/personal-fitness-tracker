# Third-party notices

Data and artwork in this project that we did not create ourselves, with the
terms each may be used under. When in doubt, the rule is: ideas are free,
MIT/Apache pieces need this attribution kept intact, AGPL pieces stay out,
and anything with unclear ownership stays out.

## Body geometry (`fitness_app/static/data/body-paths.json`)

SVG path data for the muscle map, converted to JSON from
`frontend/src/lib/body-paths.js` in the openGym reference copy. That file
derives from **MuscleMap** by Melih Colpan, used under the **MIT License**:

```
MIT License

Copyright (c) 2026 Melih Colpan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Our map renderer (`static/js/muscles.js`) is written from scratch for this
project and only consumes the geometry above. Male and female figures are
both included.

## Exercise library (`Exercise` rows with `source = "exercisedb-mit"`)

English exercise names, attributes and instructions originate from
**ExerciseDB v1** by AscendAPI, reaching us through
**hasaneyldrm/exercises-dataset**, which distributes that metadata under the
**MIT License**:

```
MIT License

Copyright (c) 2026 Hasan Emir Yıldırım

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation and data files (the "Software"),
to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Only the English metadata is used. Non-English translations in that ecosystem
are derivative works under other licences and are not imported.

## Deliberately NOT used

- **Exercise images/animations**: ownership is disputed between two parties
  (see `Resources_Archive/openGym-main/NOTICE.md`). Until provenance is
  settled they are treated as unlicensed. Nothing is bundled, hotlinked or
  cached by this project.
- **openGym application code** (components, progression engine, importer and
  coach logic): GNU AGPL v3. Ideas and training methodology are reimplemented
  where useful; no AGPL code is copied.
