"""Per-subject persistent prototype settings and private, normalized screensavers."""
import io,json,sqlite3,threading
from pathlib import Path
from PIL import Image
from .device_contract import DeviceProfile
from .visual_images import normalize

class DeviceStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.db=self.root/'profiles.sqlite';self.lock=threading.RLock()
        with sqlite3.connect(self.db) as c:c.execute('CREATE TABLE IF NOT EXISTS profiles(owner TEXT PRIMARY KEY,profile TEXT NOT NULL)')
    def profile(self,owner):
        with self.lock,sqlite3.connect(self.db) as c:
            row=c.execute('SELECT profile FROM profiles WHERE owner=?',(owner,)).fetchone()
            if row:return DeviceProfile.model_validate_json(row[0])
            profile=DeviceProfile();c.execute('INSERT INTO profiles VALUES(?,?)',(owner,profile.model_dump_json()));return profile
    def update(self,owner,body):
        allowed={'skin','screen','display','interaction_mode','keep_screen_awake'}
        if not isinstance(body,dict) or not set(body)<=allowed:raise ValueError('Unknown device setting')
        with self.lock:
            current=self.profile(owner).model_dump()
            for key,value in body.items():
                if isinstance(current.get(key),dict) and isinstance(value,dict):current[key]={**current[key],**value}
                else:current[key]=value
            profile=DeviceProfile.model_validate(current)
            with sqlite3.connect(self.db) as c:c.execute('UPDATE profiles SET profile=? WHERE owner=?',(profile.model_dump_json(),owner))
            return profile
    def asset_path(self,profile):
        path=self.root/(profile.client_id+'.jpg')
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):raise ValueError('Invalid device asset')
        return path
    def upload(self,owner,data,mime):
        if mime not in {'image/jpeg','image/png','image/webp'} or len(data)>2*1024*1024:raise ValueError('Invalid screensaver file')
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'JPEG','PNG','WEBP'} or image.width*image.height>4_000_000 or getattr(image,'is_animated',False):raise ValueError('Screensaver image policy')
        jpeg=normalize(data)['device']['bytes']
        with self.lock:
            profile=self.profile(owner);path=self.asset_path(profile);temp=path.with_suffix('.tmp')
            if temp.is_symlink():raise ValueError('Invalid asset temporary')
            temp.write_bytes(jpeg);temp.replace(path);profile.has_screensaver=True
            with sqlite3.connect(self.db) as c:c.execute('UPDATE profiles SET profile=? WHERE owner=?',(profile.model_dump_json(),owner))
        return profile
    def image(self,owner):
        profile=self.profile(owner)
        if not profile.has_screensaver:raise KeyError('No screensaver')
        return self.asset_path(profile).read_bytes()
    def remove_image(self,owner):
        with self.lock:
            profile=self.profile(owner);self.asset_path(profile).unlink(missing_ok=True);profile.has_screensaver=False
            with sqlite3.connect(self.db) as c:c.execute('UPDATE profiles SET profile=? WHERE owner=?',(profile.model_dump_json(),owner))
            return profile
