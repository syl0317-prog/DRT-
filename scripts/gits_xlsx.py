"""Minimal read-only OOXML table reader (stdlib, no workbook modification)."""
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd

def read_sheets(path):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        out = {}
        for name in sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')):
            rows = []
            for r in ET.fromstring(z.read(name)).findall('.//s:sheetData/s:row', ns):
                row = {}
                for c in r.findall('s:c', ns):
                    col = ''.join(x for x in c.attrib['r'] if x.isalpha())
                    v = c.find('s:v', ns)
                    value = v.text if v is not None else ''.join(c.find('s:is', ns).itertext()) if c.find('s:is', ns) is not None else None
                    row[col] = strings[int(value)] if c.get('t') == 's' and value is not None else value
                rows.append(row)
            f = pd.DataFrame(rows)
            out[name] = f
        return out
