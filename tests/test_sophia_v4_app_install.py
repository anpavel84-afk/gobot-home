"""Installer safety gates. All images, metadata, UART and esptool are local mocks."""
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import zlib

import pytest


SPEC=importlib.util.spec_from_file_location(
    'sophia_v4_installer',Path(__file__).resolve().parents[1]/'tools/sophia_v4_app_install.py')
installer=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def symlink_or_skip(link,target,**kwargs):
    try:link.symlink_to(target,**kwargs)
    except OSError as error:
        if getattr(error,'winerror',None)==1314 or error.errno==errno.ENOTSUP:
            pytest.skip('OS symlink creation capability unavailable (WinError 1314 or ENOTSUP); installer security unchanged')
        raise


def app_bytes(version,*,size=512,chip=9):
    data=bytearray(size)
    data[0]=0xe9;data[1]=1
    struct.pack_into('<H',data,12,chip)
    struct.pack_into('<I',data,32,0xabcd5432)
    encoded=version.encode('ascii')
    data[48:48+len(encoded)]=encoded
    return bytes(data)


def metadata(*,sequence=1,state=2,crc_valid=True):
    partition=bytearray(b'\xff'*4096)
    subtypes={'nvs':2,'otadata':0,'phy_init':1,'ota_0':0x10,'ota_1':0x11,'assets':0x82}
    for index,(name,(address,size,typ)) in enumerate(installer.EXPECTED_PARTITIONS.items()):
        struct.pack_into('<HBBII16sI',partition,index*32,0x50aa,typ,subtypes[name],
                         address,size,name.encode().ljust(16,b'\0'),0)
    ota=bytearray(b'\xff'*8192)
    struct.pack_into('<I',ota,0,sequence)
    crc=zlib.crc32(struct.pack('<I',sequence),0xffffffff)
    struct.pack_into('<II',ota,24,state,crc if crc_valid else crc^1)
    return bytes(partition),bytes(ota)


@pytest.fixture
def images(tmp_path,monkeypatch):
    current=tmp_path/'v4.bin';target=tmp_path/'candidate.bin'
    current.write_bytes(app_bytes(installer.BASELINE_VERSION))
    target.write_bytes(app_bytes('0.4.15-dev-sophia-unified-v4',size=768))
    baseline_sha=installer.sha256(current);candidate_sha=installer.sha256(target)
    # Synthetic fixture only; production constants never change on disk.
    monkeypatch.setattr(installer,'BASELINE_SHA',baseline_sha)
    monkeypatch.setattr(installer,'BASELINE_BYTES',current.stat().st_size)
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({
        'baseline_app_sha256':baseline_sha,'baseline_app_size':current.stat().st_size,
        'baseline_version':installer.BASELINE_VERSION,'app_offset':'0x20000',
        'app_slot_capacity':installer.APP_CAPACITY,'model':'wn10_sophia',
        'detector_mode':'DET_MODE_95','candidate_app_sha256':candidate_sha,
        'candidate_app_size':target.stat().st_size,'candidate_version':'0.4.15-dev-sophia-unified-v4',
    }),encoding='utf-8')
    return SimpleNamespace(current_image=current,current_sha=baseline_sha,
        target_image=target,target_sha=candidate_sha,manifest=manifest,
        expected_current_version=installer.BASELINE_VERSION,port='COM3',
        report_dir=tmp_path/'private',attempt_id='synthetic',files_only=False,execute=False)


@pytest.fixture
def simulated_device(images,monkeypatch):
    partition,ota=metadata()
    events=[]
    original_audit=installer.audit_metadata
    monkeypatch.setattr(installer,'audit_metadata',lambda part,selection:original_audit(
        part,selection,partition_sha=digest(partition),ota_sha=digest(ota)))
    def uart(port,version):
        assert port=='COM3'
        events.append(('uart',version))
        return {'version':version,'wifi':'1','enrolled':'1','phase':'0','upload':'1','muted':'0'}
    def esptool(port,operation,run_dir,stage,*,image=None,region=None):
        assert port=='COM3'
        events.append((operation,stage,region))
        if operation=='read':
            assert region in {'partition','ota'}
            image.write_bytes(partition if region=='partition' else ota)
        elif operation=='write':
            # A persisted rollback proof and exclusive marker exist before write.
            report=json.loads((run_dir/'report.json').read_text(encoding='utf-8'))
            assert report['restore_image_matches_active_flash'] is True
            markers=list(images.report_dir.glob('attempt-*.json'))
            assert len(markers)==1
            assert json.loads(markers[0].read_text())['state']=='write_started'
            assert events.index(('verify','verify-current-app',None))<len(events)-1
            assert installer.sha256(image)==images.target_sha
    monkeypatch.setattr(installer,'uart_status',uart)
    monkeypatch.setattr(installer,'run_esptool',esptool)
    return images,events,esptool


def test_default_is_readonly_and_files_only_cannot_execute():
    parsed=installer.parser().parse_args(['--current-image','v4.bin','--current-sha','a'*64,
        '--target-image','target.bin','--target-sha','b'*64,'--expected-current-version','v4',
        '--report-dir','private'])
    assert parsed.execute is False and parsed.files_only is False
    parsed.execute=True;parsed.files_only=True
    with pytest.raises(ValueError,match='files_only_cannot_execute'):installer.perform(parsed)


def test_files_only_never_touches_port_or_esptool(images,monkeypatch,capsys):
    images.files_only=True
    def denied(*args,**kwargs):pytest.fail('hardware or subprocess reached by files-only')
    monkeypatch.setattr(installer,'uart_status',denied)
    monkeypatch.setattr(installer,'run_esptool',denied)
    monkeypatch.setattr(installer.subprocess,'run',denied)
    report=installer.perform(images)
    assert report['direction']=='install_candidate'
    assert report['execute'] is False and report['app_write_started'] is False
    assert not images.report_dir.exists()
    assert json.loads(capsys.readouterr().out)['files_only']=='PASS'


def test_exact_images_can_reverse_for_restore(images):
    images.current_image,images.target_image=images.target_image,images.current_image
    images.current_sha,images.target_sha=images.target_sha,images.current_sha
    images.expected_current_version='0.4.15-dev-sophia-unified-v4'
    assert installer.validate_images(images)['direction']=='restore_v4'


@pytest.mark.parametrize('change,reason',[
    ('wrong_current_sha','images_must_be_exact'),
    ('same_images','images_must_be_exact'),
    ('wrong_expected_version','expected_current_version_mismatch'),
    ('wrong_candidate_size','app_manifest_identity_mismatch'),
    ('changed_wake','manifest_not_verified_sophia_v4_basis'),
    ('unbuilt_manifest','invalid_sha256'),
])
def test_image_manifest_gates(images,change,reason):
    value=json.loads(images.manifest.read_text())
    if change=='wrong_current_sha':images.current_sha='0'*64
    if change=='same_images':images.target_sha=images.current_sha
    if change=='wrong_expected_version':images.expected_current_version='old-version'
    if change=='wrong_candidate_size':value['candidate_app_size']+=1
    if change=='changed_wake':value['detector_mode']='DET_MODE_90'
    if change=='unbuilt_manifest':value.pop('candidate_app_sha256')
    images.manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError,match=reason):installer.validate_images(images)


@pytest.mark.parametrize('kind,reason',[
    ('tampered','app_image_sha_mismatch'),('wrong_chip','not_esp32s3'),
    ('descriptor','app_descriptor_missing'),('oversize','app_image_exceeds_ota0'),
    ('symlink','missing_or_symlink'),
])
def test_app_file_integrity_and_partition_bound(tmp_path,kind,reason):
    path=tmp_path/'app.bin';data=app_bytes('test',chip=0 if kind=='wrong_chip' else 9)
    if kind=='descriptor':data=data[:32]+b'\0'*4+data[36:]
    path.write_bytes(data);expected=digest(data)
    if kind=='tampered':path.write_bytes(data+b'bad')
    if kind=='oversize':
        with path.open('r+b') as output:output.truncate(installer.APP_CAPACITY+1)
    if kind=='symlink':
        link=tmp_path/'link.bin';symlink_or_skip(link,path);path=link
    with pytest.raises(ValueError,match=reason):installer.app_info(path,expected)


def test_exact_metadata_verifies_v4_ota0():
    partition,ota=metadata()
    report=installer.audit_metadata(partition,ota,partition_sha=digest(partition),ota_sha=digest(ota))
    assert report['active_slot']=='ota_0'
    assert report['otadata_entries'][0]=={'sector':0,'sequence':1,'state':2,'crc_valid':True}
    assert report['otadata_entries'][1]['crc_valid'] is False
    assert report['app_address']=='0x20000' and report['app_capacity']==0x3f0000


@pytest.mark.parametrize('sequence,state,crc_valid',[(2,2,True),(1,1,True),(1,0xffffffff,True),(1,2,False)])
def test_ota_selection_fails_closed(sequence,state,crc_valid):
    partition,ota=metadata(sequence=sequence,state=state,crc_valid=crc_valid)
    with pytest.raises(ValueError,match='active_ota0_not_unambiguous_valid'):
        installer.audit_metadata(partition,ota,partition_sha=digest(partition),ota_sha=digest(ota))


def test_metadata_hash_and_layout_must_both_match():
    partition,ota=metadata()
    with pytest.raises(ValueError,match='partition_table_not_exact_v4'):
        installer.audit_metadata(partition,ota)
    changed=bytearray(partition);struct.pack_into('<I',changed,3*32+4,0x30000)
    with pytest.raises(ValueError,match='partition_layout_changed'):
        installer.audit_metadata(bytes(changed),ota,partition_sha=digest(changed),ota_sha=digest(ota))
    with pytest.raises(ValueError,match='otadata_not_exact_v4'):
        installer.audit_metadata(partition,ota[:-1],partition_sha=digest(partition),ota_sha=digest(ota))


def test_uart_whitelist_allows_lan_upload_without_leaking_fields():
    status=installer.parse_status('I (123) GOBOT_STATUS version=0.4.14-dev-host-b-sophia-mic-v4 '
        'wifi=1 enrolled=1 muted=1 phase=0 upload=1 token=SECRET ssid=PRIVATE raw_samples=0')
    assert set(status)=={'version','wifi','enrolled','muted','phase','upload'}
    assert 'SECRET' not in str(status) and 'PRIVATE' not in str(status)
    installer.validate_status(status,installer.BASELINE_VERSION)
    status['phase']='1'
    with pytest.raises(ValueError,match='device_not_idle'):installer.validate_status(status,installer.BASELINE_VERSION)
    status['version']='wrong'
    with pytest.raises(ValueError,match='firmware_version_mismatch'):
        installer.validate_status(status,installer.BASELINE_VERSION)


@pytest.mark.parametrize('line',[
    'GOBOT_STATUS version=v4 wifi=1 enrolled=1 phase=0 upload=1',
    'GOBOT_STATUS version=v4 wifi=2 enrolled=1 muted=0 phase=0 upload=1',
    'unrelated token=SECRET',
])
def test_incomplete_or_invalid_uart_status_is_rejected(line):
    assert installer.parse_status(line) is None


def test_command_whitelist_has_only_exact_regions_and_app_offset():
    for name,(address,size) in installer.READ_REGIONS.items():
        cmd=installer.esptool_command('COM3','read',region=name,image='private.bin')
        assert cmd[-4:]==['read-flash',hex(address),str(size),'private.bin']
    for operation in ('verify','write'):
        cmd=installer.esptool_command('COM3',operation,image='app.bin')
        assert cmd[-9:]==[operation+'-flash','--flash-size','keep','--flash-mode','keep',
                         '--flash-freq','keep','0x20000','app.bin']
        assert cmd[cmd.index('--connect-attempts')+1]=='3'
        assert ('--no-stub' in cmd)==(operation=='verify')
        assert all('erase' not in arg for arg in cmd)
    for operation in ('erase','write-flash','nvs','full-flash','read-flash'):
        with pytest.raises(ValueError,match='flash_operation_denied'):
            installer.esptool_command('COM3',operation,image='app.bin')
    with pytest.raises(ValueError,match='flash_read_region_denied'):
        installer.esptool_command('COM3','read',region='nvs',image='private.bin')


def test_private_report_directory_rejects_symlink_parent(tmp_path):
    destination=tmp_path/'actual';destination.mkdir()
    link=tmp_path/'link';symlink_or_skip(link,destination,target_is_directory=True)
    with pytest.raises(ValueError,match='private_report_directory_symlink_denied'):
        installer.private_directory(link/'child')


def test_readonly_preflight_proves_restore_without_flash_write(simulated_device):
    images,events,_=simulated_device
    report=installer.perform(images)
    assert [event[0] for event in events]==['uart','read','read','verify']
    assert report['restore_image_matches_active_flash'] is True
    assert report['app_write_started'] is False
    assert not list(images.report_dir.glob('attempt-*.json'))


def test_execute_exact_order_postverify_and_metadata_preservation(simulated_device):
    images,events,_=simulated_device;images.execute=True
    report=installer.perform(images)
    assert [event[0] for event in events]==['uart','read','read','verify','write','verify','read','read','uart']
    assert report['app_write_verified'] is True and report['before']==report['after']
    assert report['uart_after']['upload']=='1'
    assert report['nvs_read'] is False and report['whole_flash_read'] is False
    marker=next(images.report_dir.glob('attempt-*.json'))
    assert json.loads(marker.read_text())['state']=='verified'
    previous=list(events)
    with pytest.raises(ValueError,match='attempt_marker_exists_no_automatic_retry'):installer.perform(images)
    assert events==previous


def test_current_rom_verify_failure_prevents_all_writes(simulated_device,monkeypatch):
    images,events,original=simulated_device;images.execute=True
    def failing(*args,**kwargs):
        if args[3]=='verify-current-app':raise ValueError('current_app_mismatch')
        return original(*args,**kwargs)
    monkeypatch.setattr(installer,'run_esptool',failing)
    with pytest.raises(ValueError,match='current_app_mismatch'):installer.perform(images)
    assert all(event[0]!='write' for event in events)
    assert not list(images.report_dir.glob('attempt-*.json'))


def test_partial_write_has_marker_and_never_blindly_retries(simulated_device,monkeypatch):
    images,events,original=simulated_device;images.execute=True
    def interrupted(*args,**kwargs):
        result=original(*args,**kwargs)
        if args[1]=='write':raise TimeoutError('synthetic interruption')
        return result
    monkeypatch.setattr(installer,'run_esptool',interrupted)
    with pytest.raises(TimeoutError):installer.perform(images)
    marker=next(images.report_dir.glob('attempt-*.json'))
    state=json.loads(marker.read_text())
    assert state['state']=='failed_no_retry' and state['partial_write_possible'] is True
    with pytest.raises(ValueError,match='attempt_marker_exists_no_automatic_retry'):installer.perform(images)
    assert sum(event[0]=='write' for event in events)==1


def test_metadata_changed_after_write_fails_without_retry(simulated_device,monkeypatch):
    images,events,original=simulated_device;images.execute=True
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        if args[3]=='read-ota-after':kwargs['image'].write_bytes(b'\x00'*8192)
        return result
    monkeypatch.setattr(installer,'run_esptool',changed)
    with pytest.raises(ValueError,match='otadata_not_exact_v4'):installer.perform(images)
    assert sum(event[0]=='write' for event in events)==1
    assert json.loads(next(images.report_dir.glob('attempt-*.json')).read_text())['state']=='failed_no_retry'
