"""Guarded Sophia V4 app-only install/restore. No hardware is used on import.

Default invocation performs a read-only UART/ROM preflight. --files-only avoids
the serial port entirely. --execute permits ONE write of the verified APP image
at 0x20000. No NVS, whole-flash read, erase, partition/OTA write, credentials,
runtime setting, gateway configuration or provider request is supported.

For an ordinary restore reverse current/target images and SHA values, and use
the installed candidate as --expected-current-version. A partial/unknown flash
cannot pass the current-image ROM verification and is never blindly retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
from uuid import uuid4
import zlib

ROOT=Path(__file__).resolve().parents[1]
BASELINE_VERSION='0.4.14-dev-host-b-sophia-mic-v4'
BASELINE_SHA='254793df0426fecdfafbe5047674aef896568c236dd58330b6e4a47ff9c311a2'
BASELINE_BYTES=3668912
PARTITION_SHA='ce40cfe75056ef74bc052942f8a9ee3dce8e5e14ba17a6f63685a8fa0d11a23d'
OTA_SHA='8ba3b110139f45443d4f268d1a3373ef99a1718b71d51664531b83ee2d4b91a3'
APP_OFFSET=0x20000
APP_CAPACITY=0x3f0000
READ_REGIONS={'partition':(0x8000,4096),'ota':(0xd000,8192)}
EXPECTED_PARTITIONS={
    'nvs':(0x9000,0x4000,1),'otadata':(0xd000,0x2000,1),
    'phy_init':(0xf000,0x1000,1),'ota_0':(APP_OFFSET,APP_CAPACITY,0),
    'ota_1':(0x410000,0x3f0000,0),'assets':(0x800000,0x800000,1)}


def sha256(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def fail(reason):raise ValueError(reason)


def checked_sha(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):fail('invalid_sha256')
    return value


def app_info(path,expected_sha):
    path=Path(path)
    if not path.is_file() or path.is_symlink():fail('missing_or_symlink_app_image')
    size=path.stat().st_size
    if not 256<=size<=APP_CAPACITY or ((size+4095)//4096)*4096>APP_CAPACITY:
        fail('app_image_exceeds_ota0')
    if sha256(path)!=checked_sha(expected_sha):fail('app_image_sha_mismatch')
    with path.open('rb') as source:header=source.read(256)
    if header[0]!=0xe9 or not 1<=header[1]<=16 or struct.unpack_from('<H',header,12)[0]!=9:
        fail('not_esp32s3_app_image')
    # ESP-IDF puts esp_app_desc_t at the start of the first APP segment.
    if struct.unpack_from('<I',header,32)[0]!=0xabcd5432:fail('app_descriptor_missing')
    try:version=header[48:80].split(b'\0',1)[0].decode('ascii')
    except UnicodeDecodeError:fail('invalid_app_version')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,31}',version):fail('invalid_app_version')
    return {'sha256':expected_sha,'bytes':size,'version':version,
            'partition_remaining_bytes':APP_CAPACITY-size,'chip':'esp32s3'}


def validate_images(args):
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    if (manifest.get('baseline_app_sha256')!=BASELINE_SHA or
            manifest.get('baseline_app_size')!=BASELINE_BYTES or
            manifest.get('baseline_version')!=BASELINE_VERSION or
            manifest.get('app_offset')!='0x20000' or manifest.get('app_slot_capacity')!=APP_CAPACITY or
            manifest.get('model')!='wn10_sophia' or manifest.get('detector_mode')!='DET_MODE_95'):
        fail('manifest_not_verified_sophia_v4_basis')
    candidate_sha=checked_sha(manifest.get('candidate_app_sha256'))
    candidate_size=manifest.get('candidate_app_size')
    if type(candidate_size) is not int or not 256<=candidate_size<=APP_CAPACITY:
        fail('manifest_candidate_not_built')
    if args.current_sha==args.target_sha or {args.current_sha,args.target_sha}!={BASELINE_SHA,candidate_sha}:
        fail('images_must_be_exact_v4_and_manifest_candidate')
    current=app_info(args.current_image,args.current_sha)
    target=app_info(args.target_image,args.target_sha)
    for info in (current,target):
        expected_version=BASELINE_VERSION if info['sha256']==BASELINE_SHA else manifest.get('candidate_version')
        expected_size=BASELINE_BYTES if info['sha256']==BASELINE_SHA else candidate_size
        if info['version']!=expected_version or info['bytes']!=expected_size:fail('app_manifest_identity_mismatch')
    if current['version']!=args.expected_current_version:fail('expected_current_version_mismatch')
    return {'current':current,'target':target,'direction':'restore_v4' if args.target_sha==BASELINE_SHA else 'install_candidate',
            'manifest_sha256':sha256(args.manifest),'installer_sha256':sha256(Path(__file__))}


def audit_metadata(partition,ota,*,partition_sha=PARTITION_SHA,ota_sha=OTA_SHA):
    if len(partition)!=4096 or hashlib.sha256(partition).hexdigest()!=partition_sha:
        fail('partition_table_not_exact_v4')
    if len(ota)!=8192 or hashlib.sha256(ota).hexdigest()!=ota_sha:fail('otadata_not_exact_v4')
    parts={};subtypes={}
    for offset in range(0,len(partition),32):
        magic,typ,subtype,address,size,raw_name,flags=struct.unpack_from('<HBBII16sI',partition,offset)
        if magic in {0xffff,0xebeb}:break
        if magic!=0x50aa:fail('invalid_partition_entry')
        try:name=raw_name.split(b'\0',1)[0].decode('ascii')
        except UnicodeDecodeError:fail('invalid_partition_name')
        if not name or name in parts:fail('duplicate_partition_name')
        parts[name]=(address,size,typ);subtypes[name]=subtype
    if parts!=EXPECTED_PARTITIONS or subtypes.get('ota_0')!=0x10 or subtypes.get('ota_1')!=0x11:
        fail('partition_layout_changed')
    records=[]
    for sector in range(2):
        base=sector*4096
        sequence=struct.unpack_from('<I',ota,base)[0]
        state,crc=struct.unpack_from('<II',ota,base+24)
        valid=(sequence not in {0,0xffffffff} and crc==zlib.crc32(struct.pack('<I',sequence),0xffffffff))
        records.append({'sector':sector,'sequence':sequence,'state':state,'crc_valid':valid})
    eligible=[item for item in records if item['crc_valid'] and item['state']==2]
    if not eligible or any((item['sequence']-1)%2!=0 for item in eligible):fail('active_ota0_not_unambiguous_valid')
    return {'partition_sha256':partition_sha,'otadata_sha256':ota_sha,'active_slot':'ota_0',
            'app_address':hex(APP_OFFSET),'app_capacity':APP_CAPACITY,'otadata_entries':records}


def parse_status(line):
    if 'GOBOT_STATUS ' not in line:return None
    values=dict(re.findall(r'\b(version|wifi|enrolled|muted|phase|upload)=([A-Za-z0-9_.-]{1,80})\b',line))
    if set(values)!={'version','wifi','enrolled','muted','phase','upload'}:return None
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,31}',values['version']):return None
    for key in ('wifi','enrolled','muted','upload'):
        if values[key] not in {'0','1'}:return None
    if not values['phase'].isdigit() or len(values['phase'])>2:return None
    return values


def validate_status(values,expected_version):
    if values['version']!=expected_version:fail('uart_firmware_version_mismatch')
    if values['wifi']!='1' or values['enrolled']!='1' or values['phase']!='0':
        fail('device_not_idle_wifi_enrolled')
    # upload=1 may be the explicitly negotiated local LAN stream, not cloud audio.
    # User Mute is observed, never changed or treated as permission to unmute.


def uart_status(port,expected_version):
    import serial
    from serial.tools import list_ports
    ports=[item for item in list_ports.comports() if item.device.upper()==port.upper()]
    if len(ports)!=1 or (ports[0].vid,ports[0].pid)!=(0x303a,0x1001):fail('wrong_esp32s3_usb_interface')
    uart=serial.Serial(port=None,baudrate=115200,timeout=.2,write_timeout=2,dsrdtr=False,rtscts=False)
    uart.port=port;uart.dtr=False;uart.rts=False
    try:
        uart.open();uart.reset_input_buffer()
        deadline=time.monotonic()+35;next_query=0;observed=None;buffer=b''
        while time.monotonic()<deadline:
            if time.monotonic()>=next_query:
                uart.write(b'GOBOT_STATUS\n');next_query=time.monotonic()+2
            buffer=(buffer+uart.read(4096))[-16384:]
            lines=buffer.split(b'\n');buffer=lines.pop()
            for line in lines:
                values=parse_status(line.decode('utf-8',errors='ignore'))
                if values is None:continue
                observed=values
                if values['version']!=expected_version:fail('uart_firmware_version_mismatch')
                if values['wifi']=='1' and values['enrolled']=='1' and values['phase']=='0':
                    validate_status(values,expected_version);return values
        fail('uart_ready_not_confirmed')
    finally:uart.close()


def esptool_command(port,operation,*,image=None,region=None):
    base=[sys.executable,'-m','esptool','--chip','esp32s3','--port',port,
          '--baud','460800','--connect-attempts','3','--before','default-reset','--after','hard-reset']
    if operation=='read':
        if region not in READ_REGIONS:fail('flash_read_region_denied')
        address,size=READ_REGIONS[region]
        return base+['read-flash',hex(address),str(size),str(image)]
    if operation not in {'verify','write'}:fail('flash_operation_denied')
    # ESP32-S3 ROM supports MD5 verification; no RAM stub is needed for this
    # proof that the preserved current image matches the active APP region.
    if operation=='verify':base.append('--no-stub')
    return base+[operation+'-flash','--flash-size','keep','--flash-mode','keep','--flash-freq','keep',
                 hex(APP_OFFSET),str(image)]


def run_esptool(port,operation,run_dir,stage,*,image=None,region=None):
    argv=esptool_command(port,operation,image=image,region=region)
    print(json.dumps({'stage':stage,'operation':operation,'flash_write':operation=='write'}),flush=True)
    # Raw USB/tool output can contain board IDs. It stays in the private directory.
    with (run_dir/(stage+'.log')).open('xb') as log:
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                              timeout=180 if operation=='write' else 120,check=False)
    if result.returncode:fail('esptool_'+stage+'_failed')


def private_directory(path):
    path=Path(os.path.abspath(path))
    if any(item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction())
           for item in (path,*path.parents)):
        fail('private_report_directory_symlink_denied')
    path=path.resolve()
    if path.is_relative_to(ROOT):
        probe=subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet','--',str(path.relative_to(ROOT))],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        if probe.returncode:fail('private_report_directory_must_not_be_git_content')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path


def save_json(path,value,*,exclusive=False):
    with path.open('x' if exclusive else 'w',encoding='utf-8') as target:
        json.dump(value,target,ensure_ascii=False,indent=2);target.flush();os.fsync(target.fileno())


def perform(args):
    if not re.fullmatch(r'COM[1-9][0-9]*',args.port,re.I):fail('explicit_windows_usb_port_required')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.attempt_id):fail('invalid_attempt_id')
    if args.files_only and args.execute:fail('files_only_cannot_execute')
    report=validate_images(args)
    report.update(schema='sophia_v4_app_install_v1',execute=bool(args.execute),app_write_started=False,
                  app_write_verified=False,automatic_retry=False,non_app_write_allowed=False,
                  nvs_read=False,whole_flash_read=False,backend_quiescence_checked_by_installer=False)
    if args.files_only:
        print(json.dumps({'files_only':'PASS',**report}),flush=True)
        return report
    private=private_directory(args.report_dir)
    marker=private/('attempt-'+args.attempt_id+'-'+args.current_sha[:12]+'-'+args.target_sha[:12]+'.json')
    if marker.exists() or marker.is_symlink():fail('attempt_marker_exists_no_automatic_retry')
    run_dir=private/('preflight-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid4().hex[:8])
    run_dir.mkdir(mode=0o700)
    current=run_dir/'current-app.bin';target=run_dir/'target-app.bin'
    shutil.copyfile(args.current_image,current);shutil.copyfile(args.target_image,target)
    app_info(current,args.current_sha);app_info(target,args.target_sha)
    write_attempted=False
    try:
        report['uart_before']=uart_status(args.port,args.expected_current_version)
        for name in READ_REGIONS:
            run_esptool(args.port,'read',run_dir,'read-'+name+'-before',image=run_dir/(name+'-before.bin'),region=name)
        report['before']=audit_metadata((run_dir/'partition-before.bin').read_bytes(),(run_dir/'ota-before.bin').read_bytes())
        run_esptool(args.port,'verify',run_dir,'verify-current-app',image=current)
        report['restore_image_matches_active_flash']=True
        save_json(run_dir/'report.json',report)
        if not args.execute:
            print(json.dumps({'preflight':'PASS','flash_write':False,'restore_image_matches_active_flash':True}),flush=True)
            return report
        # Exclusive, durable marker precedes the sole write. No resume/force path.
        save_json(marker,{'state':'write_started','current_sha256':args.current_sha,'target_sha256':args.target_sha,
                          'app_address':hex(APP_OFFSET),'report_directory':str(run_dir),'automatic_retry':False},exclusive=True)
        app_info(current,args.current_sha);app_info(target,args.target_sha)
        write_attempted=True;report['app_write_started']=True
        run_esptool(args.port,'write',run_dir,'write-target-app',image=target)
        run_esptool(args.port,'verify',run_dir,'verify-target-app',image=target)
        report['app_write_verified']=True
        for name in READ_REGIONS:
            run_esptool(args.port,'read',run_dir,'read-'+name+'-after',image=run_dir/(name+'-after.bin'),region=name)
        report['after']=audit_metadata((run_dir/'partition-after.bin').read_bytes(),(run_dir/'ota-after.bin').read_bytes())
        if report['after']!=report['before']:fail('metadata_changed_after_app_write')
        report['uart_after']=uart_status(args.port,report['target']['version'])
        report['status']='app_verified_metadata_preserved_boot_ready'
        save_json(marker,{'state':'verified','current_sha256':args.current_sha,'target_sha256':args.target_sha,
                          'report_directory':str(run_dir),'automatic_retry':False})
        print(json.dumps({'installation':'APP_VERIFIED','version':report['target']['version'],
                          'partition_and_ota_unchanged':True,'human_acceptance':False}),flush=True)
        return report
    except BaseException as error:
        report['status']='failed';report['error_type']=type(error).__name__
        if isinstance(error,ValueError):report['reason']=str(error)
        report['partial_write_possible']=write_attempted and not report['app_write_verified']
        if write_attempted:
            save_json(marker,{'state':'failed_no_retry','current_sha256':args.current_sha,'target_sha256':args.target_sha,
                'partial_write_possible':report['partial_write_possible'],'report_directory':str(run_dir),'automatic_retry':False})
        raise
    finally:save_json(run_dir/'report.json',report)


def parser():
    value=argparse.ArgumentParser(description=__doc__)
    value.add_argument('--current-image',type=Path,required=True)
    value.add_argument('--current-sha',type=checked_sha,required=True)
    value.add_argument('--target-image',type=Path,required=True)
    value.add_argument('--target-sha',type=checked_sha,required=True)
    value.add_argument('--expected-current-version',required=True)
    value.add_argument('--manifest',type=Path,default=ROOT/'firmware/spotpear/host/sophia_unified_v4_manifest.json')
    value.add_argument('--report-dir',type=Path,required=True)
    value.add_argument('--port',default='COM3')
    value.add_argument('--attempt-id',default='install')
    value.add_argument('--files-only',action='store_true')
    value.add_argument('--execute',action='store_true')
    return value


if __name__=='__main__':
    try:perform(parser().parse_args())
    except Exception as error:
        # Never echo esptool output, complete UART lines, paths or private settings.
        print(json.dumps({'status':'BLOCKED_OR_FAILED','error_type':type(error).__name__,
                          'reason':str(error) if isinstance(error,ValueError) else 'inspect_private_report',
                          'automatic_retry':False}),flush=True)
        raise SystemExit(1)
