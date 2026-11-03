# -*- coding: utf-8 -*-
import sys
import os
import zipfile
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')

def read_docx(path):
    print(f"\n==========================================")
    print(f"Reading: {os.path.basename(path)}")
    print(f"==========================================")
    try:
        with zipfile.ZipFile(path, 'r') as z:
            xml_data = z.read('word/document.xml')
            root = ET.fromstring(xml_data)
            texts = []
            for elem in root.iter():
                if elem.tag.endswith('}t') or elem.tag == 't':
                    if elem.text:
                        texts.append(elem.text)
            full_text = '\n'.join(texts)
            print(full_text[:3000])
    except Exception as e:
        print(f"Error: {e}")

tram_docs = [
    r"C:\Users\User\OneDrive\Desktop\성남-위례 DRT\트램.docx",
    r"C:\Users\User\OneDrive\Desktop\성남-위례 DRT\트램 연계 성남.docx",
    r"C:\Users\User\OneDrive\Desktop\성남.docx"
]

for doc in tram_docs:
    if os.path.exists(doc):
        read_docx(doc)
    else:
        print(f"Not found: {doc}")
