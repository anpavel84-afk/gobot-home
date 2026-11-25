/* Owner memory controls against an entirely local, synthetic API. No providers. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');

(async()=>{
  const browser=await chromium.launch({headless:true,
    ...(fs.existsSync('/usr/bin/chromium')?{executablePath:'/usr/bin/chromium'}:{}),args:['--no-sandbox']});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[],writes=[];
    page.on('pageerror',error=>errors.push(error.message));
    const policy={enabled:true,ttl_seconds:43200,persist:true,
      summarize:true,background:true,supplement:true};
    const status={available:true,enabled:true,policy,trigger:'every_question',
      supplements_per_question:1,private_archive:false,
      working:{available_exchanges:4,completed_exchanges:3,version:7,
        restored_exchanges:2,persisted:true,summary_kind:'grounded_semantic_working_summary'},
      lookup:{state:'delivered_late',queries:8,useful_results:3,supplements:1,last_lookup_ms:14},
      summary_worker:{last_state:'applied',global_tokens_used_or_reserved:800,
        daily_token_limit:4000,unknown_usage_attempts:0}};
    let failNext=false,loseNextAck=false;
    const response=()=>({memory:status,observed_at:Date.now()/1000});
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      assert.equal(url.origin,'http://sophia.test');
      if(url.pathname==='/api/sophia/admin/snapshot')return route.fulfill({json:{
        target:{id:'fixture-column'},revision:'fixture-revision',
        settings:{weather:{enabled:true,provider:'open_meteo',location_name:'Fixture city'}},
        changes:[],observed_at:Date.now()/1000,runtime:{status:'connected',gateway_fresh:true,
          device:{device_protocol_confirmed:true},brain:{sessions:[{ready:true,state:'ready',generation_allowed:true}]}}}});
      if(url.pathname==='/api/sophia/admin/memory'){
        assert.equal(url.search,'');
        if(request.method()==='POST'){
          const data=request.postDataJSON();writes.push(data);
          if(failNext){failNext=false;return route.fulfill({status:409,json:{detail:'working_memory_change_requires_idle'}});}
          if(data.action==='configure'){
            assert.deepEqual(Object.keys(data).sort(),['action','values']);
            assert.deepEqual(Object.keys(data.values).sort(),Object.keys(policy).sort());
            Object.assign(policy,data.values);status.enabled=policy.enabled;
          } else {
            assert.deepEqual(data,{action:'clear',confirm:true});
            status.working.available_exchanges=0;status.working.completed_exchanges=0;
          }
          if(loseNextAck){loseNextAck=false;return route.abort('failed');}
          return route.fulfill({json:{...response(),accepted:true}});
        }
        return route.fulfill({json:response()});
      }
      const name=url.pathname.replace('/sophia/settings/','')||'index.html';
      assert(['index.html','admin.js','admin.css','catalog.js','mark.svg'].includes(name),url.pathname);
      const contentType={'html':'text/html','js':'text/javascript','css':'text/css','svg':'image/svg+xml'}[name.split('.').pop()];
      return route.fulfill({body:fs.readFileSync(path.join('services/phone/dist/admin',name)),contentType});
    });
    await page.goto('http://sophia.test/sophia/settings/#/privacy');
    await page.locator('#memory-ttl:not([disabled])').waitFor();
    assert.equal(await page.locator('#memory-ttl').inputValue(),'43200');
    assert((await page.locator('#main').innerText()).includes('800 / 4000 токенов'));
    assert.equal(writes.length,0);

    await page.selectOption('#memory-ttl','14400');
    await page.locator('#reviewButton').click();
    assert((await page.locator('#dialogContent').innerText()).includes('12 ч'));
    assert((await page.locator('#dialogContent').innerText()).includes('4 ч'));
    assert.equal(writes.length,0);
    await page.locator('[data-action="memory-apply"]').click();
    await page.waitForFunction(()=>!document.getElementById('settingsDialog').open);
    assert.equal(writes.length,1);assert.equal(policy.ttl_seconds,14400);
    assert.equal(await page.locator('#reviewButton').isDisabled(),true);

    await page.locator('[data-action="memory-clear"]').click();
    await page.getByRole('button',{name:'Отмена',exact:true}).click();
    assert.equal(writes.length,1);assert.equal(status.working.available_exchanges,4);
    await page.locator('[data-action="memory-clear"]').click();
    await page.locator('[data-action="memory-clear-confirm"]').click();
    await page.waitForFunction(()=>!document.getElementById('settingsDialog').open);
    assert.equal(writes.length,2);assert.equal(status.working.available_exchanges,0);

    failNext=true;
    await page.selectOption('#memory-ttl','3600');
    await page.locator('[data-action="memory-review"]').click();
    await page.locator('[data-action="memory-apply"]').click();
    await page.waitForFunction(()=>!document.getElementById('settingsDialog').open);
    assert.equal(policy.ttl_seconds,14400);assert.equal(writes.length,3);
    assert((await page.locator('#main').innerText()).includes('Сейчас идёт разговор'));
    assert.equal(await page.locator('#memory-ttl').isDisabled(),true);
    await page.locator('[data-action="memory-refresh"]').click();
    await page.locator('#memory-ttl:not([disabled])').waitFor();

    loseNextAck=true;
    await page.locator('[data-action="memory-review"]').click();
    await page.locator('[data-action="memory-apply"]').click();
    await page.waitForFunction(()=>!document.getElementById('settingsDialog').open);
    assert.equal(writes.length,4);assert.equal(policy.ttl_seconds,3600);
    assert((await page.locator('#toast').innerText()).includes('Подтверждение изменения памяти не получено'));
    assert.equal(await page.locator('#memory-ttl').isDisabled(),true);
    await page.locator('[data-action="memory-refresh"]').click();
    await page.locator('#memory-ttl:not([disabled])').waitFor();
    assert.equal(writes.length,4);assert.equal(await page.locator('#reviewButton').isDisabled(),true);

    await page.selectOption('#memory-ttl','86400');
    policy.ttl_seconds=43200;
    await page.locator('[data-action="memory-refresh"]').click();
    await page.getByRole('button',{name:'Загрузить значения сервера',exact:true}).waitFor();
    assert.equal(await page.locator('#memory-ttl').isDisabled(),true);
    await page.locator('[data-action="memory-discard"]').click();
    await page.locator('#memory-ttl:not([disabled])').waitFor();
    assert.equal(await page.locator('#memory-ttl').inputValue(),'43200');
    assert.equal(writes.length,4);
    await page.screenshot({path:'/tmp/gobot-working-memory-admin-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
    await page.screenshot({path:'/tmp/gobot-working-memory-admin-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: owner memory settings, review, clear confirmation, busy refusal, lost acknowledgement, stale draft, desktop and mobile.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
