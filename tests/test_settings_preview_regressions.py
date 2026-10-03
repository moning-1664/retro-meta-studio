from app.plan import transfer
from bridge.api import Api

def test_equal_media_retained_for_preview_not_copied(tmp_path):
    source=tmp_path/"source.png";source.write_bytes(b"x"*10)
    item={'system':'msx','filename':'1942.zip','fields':{'name':'New title'},'media':[{'type':'covers','path':str(source),'size':10}], 'rom':None}
    existing={'system':'msx','filename':'1942.zip','fields':{'name':'Old title'},'present':True,'media':[{'media_type':'covers','rel_path':'target.png','size':10}]}
    prepared,reason=transfer.decide(item,existing,'overwrite')
    assert prepared['media']==[]
    assert prepared['previewMedia']==item['media']
    class Dummy:
        _paste_ops={'operation':{'prepared':[prepared]}}
        def _encode_image(self,path,maximum):return 'encoded:'+path
    result=Api.paste_preview_media(Dummy(),'operation','msx|1942.zip','covers')
    assert result=={'ok':True,'data':'encoded:'+str(source)}
