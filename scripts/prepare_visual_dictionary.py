"""Install pinned dictionary data inside vendor; no executable install or tar extraction."""
import hashlib,io,json,re,sys,tarfile,unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx

ROOT=Path(__file__).resolve().parents[1]
URL='https://download.freedict.org/dictionaries/rus-eng/2025.11.23/freedict-rus-eng-2025.11.23.src.tar.xz'
SHA512='9adf7a5eda27ccfa3e496b86b2fd575fc0e4af7ac5626a219d44e4ebfd56280deaf67cefd995ab04e9d7ef415e88f8cf0f9cae3252da6221376fd6d0c39012ba'
LICENSE='https://creativecommons.org/licenses/by-sa/3.0/'
NS={'t':'http://www.tei-c.org/ns/1.0'}

def clean(text):return unicodedata.normalize('NFC',text.replace('\u0301','')).casefold().replace('ё','е').strip()

def build_lexicon(data):
    # Input is a SHA-pinned public release, not arbitrary uploads; no external DTD lookup.
    if len(data)>20_000_000 or b'<!ENTITY' in data:raise ValueError('Dictionary XML policy')
    root=ET.fromstring(data)
    if root.find('.//t:availability/t:p/t:ref',NS).get('target')!=LICENSE+'legalcode':raise ValueError('Unexpected dictionary license')
    entries={}
    for entry in root.findall('.//t:entry',NS):
        word=clean(entry.findtext('t:form/t:orth','',NS));pos=entry.findtext('t:gramGrp/t:pos','',NS)
        if pos not in {'n','adj'} or not re.fullmatch(r'[а-я -]{1,80}',word):continue
        senses=[]
        for sense in entry.findall('t:sense',NS):
            terms=[]
            for quote in sense.findall('t:cit[@type="trans"]/t:quote',NS):
                term=' '.join(''.join(quote.itertext()).split()).strip()
                if re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,79}",term) and term.casefold() not in {t.casefold() for t in terms}:terms.append(term)
            if terms and terms not in senses:senses.append(terms[:5])
        if senses:
            row=entries.setdefault(word,{'pos':pos,'senses':[]})
            for sense in senses:
                if sense not in row['senses']:row['senses'].append(sense)
    return {'version':'FreeDict/WikDict rus-eng 2025.11.23','source':URL,'source_sha512':SHA512,
            'license':'CC BY-SA 3.0','license_url':LICENSE,'attribution':'Karl Bartel; WikDict, Wiktionary contributors, DBnary, FreeDict',
            'changes':'Noun/adjective headwords and English translations extracted, stress/case normalized; definitions omitted',
            'entries':entries}

def main():
    folder=ROOT/'vendor/dictionaries';folder.mkdir(parents=True,exist_ok=True)
    path=folder/URL.rsplit('/',1)[1]
    if path.exists():raw=path.read_bytes()
    else:
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=25) as client:
            with client.stream('GET',URL) as response:
                response.raise_for_status();body=bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>2_000_000:raise ValueError('Dictionary download limit')
        raw=bytes(body)
    if hashlib.sha512(raw).hexdigest()!=SHA512:raise ValueError('Dictionary release checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:xz') as archive:
        member=archive.getmember('rus-eng/rus-eng.tei')
        if not member.isfile() or member.size>20_000_000:raise ValueError('Invalid dictionary member')
        document=build_lexicon(archive.extractfile(member).read(member.size+1))
        license_member=archive.getmember('rus-eng/COPYING')
        if not license_member.isfile() or license_member.size>100_000:raise ValueError('Invalid license member')
        license_data=archive.extractfile(license_member).read(license_member.size+1)
    # Only known owned filenames are written; no archive path is ever extracted.
    if not path.exists():path.write_bytes(raw)
    (folder/'FREEDICT-LICENSE.txt').write_bytes(license_data)
    output=json.dumps(document,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    temporary=folder/'rus-eng.json.tmp';temporary.write_bytes(output);temporary.replace(folder/'rus-eng.json')
    print('Local image-query dictionary:',len(document['entries']),'headwords;',len(output),'bytes; CC BY-SA 3.0; no API/model calls')

if __name__=='__main__':main()
