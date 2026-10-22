/* Optional development dependency: npm install --no-save --package-lock=false playwright */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

(async()=>{
 const root=path.resolve(__dirname,'..');
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'vtd-browser-'));
 const output=path.join(temp,'demo');
 const server=spawn(process.env.PYTHON||'python3',[path.join(root,'scripts/demo.py'),'--output',output,'--serve','--port','0'],{cwd:root,stdio:['ignore','pipe','pipe']});
 let browser;
 try{
  const url=await new Promise((resolve,reject)=>{
   let text='';const timer=setTimeout(()=>reject(new Error('Demo server startup timed out')),15000);
   server.stdout.on('data',b=>{text+=b.toString();const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});
   server.on('exit',code=>{clearTimeout(timer);reject(new Error('Demo server exited '+code));});
  });
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1280,height:900},acceptDownloads:true});
  const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  const settled=()=>page.waitForFunction(()=>!document.getElementById('statistics').hasAttribute('aria-busy'));
  const amounts=()=>page.locator('#categoryRows tr').evaluateAll(rows=>rows.map(row=>Array.from(row.querySelectorAll('td')).slice(1).map(td=>Number(td.title.replace(/[^0-9]/g,'')))));
  await page.goto(url);await page.locator('#categoryRows tr').first().waitFor();await settled();
  assert.ok(await page.locator('#demoBanner').isVisible());
  const index=await (await page.request.get(url+'/data/index.json')).json();
  const monthId=await page.locator('#periodInput').inputValue();
  const month=await (await page.request.get(url+'/data/'+monthId.slice(0,7)+'.json')).json();
  const dayExpected=Object.values(month.days[monthId]).reduce((s,v)=>s+v.upload+v.download,0);
  const dayActual=(await amounts()).reduce((s,r)=>s+r[2],0);assert.equal(dayActual,dayExpected);
  assert.equal(await page.locator('#categoryRows tr').count(),index.categories.length);
  assert.ok(await page.locator('#restoreDayButton').isHidden());
  assert.equal(await page.locator('.hour-button[aria-pressed="true"]').count(),0);
  const dailyMetrics=await page.locator('.metrics').textContent();
  assert.equal(await page.locator('.hour-button').count(),24);
  assert.equal(await page.locator('#hourlyAxis .hourly-tick').count(),5,'hourly chart needs a numeric vertical scale');
  const verifyAxis=async(target=page)=>{
   const geometry=await target.evaluate(()=>{
    const axis=document.getElementById('hourlyAxis'),chart=document.getElementById('hourlyChart'),grid=chart.querySelector('.hourly-grid');
    return{max:Number(axis.dataset.max),unit:document.getElementById('hourlyUnit').textContent,
     ticks:[...axis.children].map(t=>({bytes:Number(t.dataset.bytes),y:t.getBoundingClientRect().top+t.getBoundingClientRect().height/2})),
     lines:[...grid.children].map(l=>l.getBoundingClientRect().bottom),height:grid.getBoundingClientRect().height,
     bars:[...chart.querySelectorAll('.hour-button[data-known="true"]')].map(b=>({total:Number(b.dataset.upload)+Number(b.dataset.download),height:b.querySelector('.hour-bars').getBoundingClientRect().height,bottom:b.querySelector('.hour-bars').getBoundingClientRect().bottom})),baseline:grid.getBoundingClientRect().bottom};
   });
   assert.ok(Number.isFinite(geometry.max)&&geometry.max>0);
   assert.equal(geometry.ticks.length,5);assert.equal(geometry.ticks[0].bytes,0);assert.equal(geometry.ticks[4].bytes,geometry.max);
   geometry.ticks.forEach((t,i)=>{assert.ok(Math.abs(t.y-geometry.lines[i])<1,'tick and horizontal gridline must align');if(i)assert.ok(t.bytes>geometry.ticks[i-1].bytes);});
   geometry.bars.forEach(b=>{assert.ok(b.total<=geometry.max);assert.ok(Math.abs(b.height-b.total/geometry.max*geometry.height)<0.1,'bar height must match byte scale');assert.ok(Math.abs(b.bottom-geometry.baseline)<1,'bars must start at zero baseline');});
   return geometry;
  };
  const initialScale=await verifyAxis();
  const hourlySum=()=>page.locator('.hour-button[data-known="true"]').evaluateAll(rows=>rows.reduce((s,r)=>s+Number(r.dataset.upload)+Number(r.dataset.download),0));
  assert.equal(await hourlySum(),dayActual);
  const hour=Object.keys(month.hourly[monthId]).sort()[0];
  await page.locator(`.hour-button[data-hour="${hour}"]`).click();
  const hourExpected=Object.values(month.hourly[monthId][hour]).reduce((s,v)=>s+v.upload+v.download,0);
  assert.equal(Number(await page.locator('#hourlyDetail').getAttribute('data-total')),hourExpected);
  assert.equal(await page.locator(`.hour-button[data-hour="${hour}"]`).getAttribute('aria-pressed'),'true');
  assert.equal((await amounts()).reduce((sum,row)=>sum+row[2],0),hourExpected,'clicked hour must filter category breakdown');
  const verifyBreakdown=async(selectedHour)=>{
   const values=month.hourly[monthId][selectedHour];
   const rows=await page.locator('#categoryRows tr').evaluateAll(rows=>rows.map(row=>({id:row.dataset.category,bytes:[...row.cells].slice(1).map(td=>Number(td.title.replace(/[^0-9]/g,''))),share:Number(row.querySelector('.category-share').dataset.share)})));
   const total=Object.values(values).reduce((sum,v)=>sum+v.upload+v.download,0);
   for(const row of rows){const expected=values[row.id]||{upload:0,download:0};assert.deepEqual(row.bytes,[expected.upload,expected.download,expected.upload+expected.download]);assert.equal(row.share,total?(expected.upload+expected.download)/total:0);}
   assert.equal(rows.length,index.categories.length);assert.ok(rows.every((row,i)=>!i||rows[i-1].bytes[2]>=row.bytes[2]));
   assert.equal(await page.locator('#categoryScope').getAttribute('data-scope'),'hour');
   assert.ok((await page.locator('#categoryScope').textContent()).includes(selectedHour+':00'));
   assert.equal(await page.locator('.metrics').textContent(),dailyMetrics,'top metrics must stay daily');
   assert.ok(await page.locator('#restoreDayButton').isVisible());
   assert.equal(await page.locator('#domainToggle').count(),0,'daily domain list must not be presented as hourly');
  };
  await verifyBreakdown(hour);
  const hourDownloading=page.waitForEvent('download');await page.click('#exportButton');
  const hourDownload=await hourDownloading,hourCsvPath=path.join(temp,'hour.csv');await hourDownload.saveAs(hourCsvPath);
  const hourCsv=(await fs.readFile(hourCsvPath,'utf8')).trim().split('\n');
  assert.equal(hourCsv.slice(1).reduce((sum,line)=>sum+Number(line.trim().split(',').at(-1).replaceAll('"','')),0),hourExpected);
  assert.ok(hourCsv[1].includes(monthId+' '+hour+':00'));assert.ok(hourDownload.suggestedFilename().includes('-'+hour+'时.csv'));
  await page.click('#refreshButton');await settled();await verifyBreakdown(hour);

  await page.selectOption('#hourlyCategory','google');
  const filteredScale=await verifyAxis();assert.ok(filteredScale.max<initialScale.max,'category filter must rescale the axis');
  assert.equal(await hourlySum(),month.days[monthId].google.upload+month.days[monthId].google.download);
  assert.equal((await amounts()).reduce((s,r)=>s+r[2],0),hourExpected);
  await verifyBreakdown(hour);
  await page.selectOption('#hourlyCategory','all');
  await page.click('#restoreDayButton');
  assert.equal((await amounts()).reduce((s,r)=>s+r[2],0),dayActual);
  assert.equal(await page.locator('#categoryScope').getAttribute('data-scope'),'day');
  assert.equal(await page.locator('.hour-button[aria-pressed="true"]').count(),0);
  const oldDay=Object.keys(month.days).filter(d=>d<monthId).sort().at(-1);
  if(oldDay){await page.locator(`.hour-button[data-hour="${hour}"]`).click();await page.locator('#periodInput').fill(oldDay);await page.locator('#periodInput').dispatchEvent('change');await settled();
   assert.equal(await hourlySum(),Object.values(month.days[oldDay]).reduce((s,v)=>s+v.upload+v.download,0));
   assert.equal(await page.locator('.hour-button[data-known="true"]').count(),24);
   assert.ok(await page.locator('#restoreDayButton').isHidden());assert.equal(await page.locator('#categoryScope').getAttribute('data-scope'),'day');
   await page.locator('.hour-button[data-hour="23"]').click();assert.ok((await page.locator('#categoryScope').textContent()).includes('23:00–24:00'));
   assert.equal((await amounts()).reduce((sum,row)=>sum+row[2],0),Object.values(month.hourly[oldDay]['23']).reduce((sum,v)=>sum+v.upload+v.download,0));
   await page.click('#todayButton');await settled();}
  await page.click('#domainToggle');await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20);
  assert.equal(await page.locator('#domainToggle').getAttribute('aria-expanded'),'true');
  assert.equal((await amounts()).reduce((s,r)=>s+r[2],0),dayActual);
  const domains=await (await page.request.get(url+'/data/domains-'+monthId.slice(0,7)+'.json')).json();
  const domainCounts=()=>page.locator('#domainRows tr').evaluateAll(rows=>rows.map(r=>({host:r.cells[0].textContent,count:Number(r.cells[1].textContent.replaceAll(',',''))})));
  assert.deepEqual(await domainCounts(),domains.days[monthId].domains.slice(0,20).map(r=>({host:r.domain,count:r.connections})));
  await page.locator(`.hour-button[data-hour="${hour}"]`).click();await verifyBreakdown(hour);
  assert.ok(await page.locator('#domainPanel').isHidden());
  await page.click('#restoreDayButton');await page.click('#domainToggle');
  await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20);

  await page.click('#domainNext');assert.equal(await page.locator('#domainRows tr').count(),5);
  await page.locator('#domainSearch').fill('very-long');assert.equal(await page.locator('#domainRows tr').count(),1);
  await page.locator('#domainSearch').fill('does-not-exist');assert.equal(await page.locator('#domainRows tr').count(),0);
  await page.locator('#domainSearch').fill('');
  await page.click('#monthTab');await settled();
  await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20&&!document.getElementById('domainStatus').textContent.includes('正在读取'));
  assert.deepEqual(await domainCounts(),domains.monthly.domains.slice(0,20).map(r=>({host:r.domain,count:r.connections})));
  assert.ok(await page.locator('#hourlyPanel').isHidden());
  assert.ok(await page.locator('#restoreDayButton').isHidden());
  assert.equal(await page.locator('#categoryScope').getAttribute('data-scope'),'month');
  const monthActual=(await amounts()).reduce((s,r)=>s+r[2],0);
  assert.equal(monthActual,index.month_totals[monthId.slice(0,7)].upload+index.month_totals[monthId.slice(0,7)].download);
  const downloading=page.waitForEvent('download');await page.click('#exportButton');
  const download=await downloading;const csvPath=path.join(temp,'export.csv');await download.saveAs(csvPath);
  const lines=(await fs.readFile(csvPath,'utf8')).trim().split('\n');assert.equal(lines.length,index.categories.length+1);
  const csvTotal=lines.slice(1).reduce((s,l)=>s+Number(l.trim().split(',').at(-1).replaceAll('"','')),0);assert.equal(csvTotal,monthActual);
  await page.locator('#periodInput').fill('1900-01');await page.locator('#periodInput').dispatchEvent('change');await settled();
  await page.waitForFunction(()=>document.getElementById('domainStatus').textContent.includes('没有收录'));
  assert.equal(await page.locator('#domainRows tr').count(),0);
  assert.ok(await page.locator('#empty').isVisible());assert.ok(await page.locator('#exportButton').isDisabled());
  await page.click('#todayButton');await settled();await page.locator('.trend-button').first().click();await settled();
  assert.equal(await page.locator('#dayTab').getAttribute('aria-selected'),'true');
  await page.click('#todayButton');await settled();await page.click('#refreshButton');await settled();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20);
  assert.ok(await page.locator('#domainPanel').isVisible());
  if(process.env.VTD_SCREENSHOT){
   const lastHour=Object.keys(month.hourly[monthId]).sort().at(-1);
   await page.locator(`.hour-button[data-hour="${lastHour}"]`).click();await verifyBreakdown(lastHour);
   await page.screenshot({path:process.env.VTD_SCREENSHOT,fullPage:true});
   await page.click('#restoreDayButton');await page.click('#domainToggle');
   await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20);
  }
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#domainSearch').fill('very-long');
  assert.ok(await page.locator('#domainRows td').first().isVisible());
  await page.click('#domainClose');await page.locator('#domainPanel').waitFor({state:'hidden'});assert.ok(await page.locator('#domainPanel').isHidden());
  await page.click('#domainToggle');await page.waitForFunction(()=>document.getElementById('domainRows').children.length===20);
  assert.ok(await page.locator('#exportButton').isVisible());assert.deepEqual(errors,[]);
  await page.locator('#hourlyPanel').scrollIntoViewIfNeeded();
  const axisX=(await page.locator('#hourlyAxis').boundingBox()).x;
  const scroll=page.locator('#hourlyScroll');await scroll.evaluate(el=>el.scrollLeft=0);await scroll.hover();
  await page.mouse.wheel(500,0);await page.waitForFunction(()=>document.getElementById('hourlyScroll').scrollLeft>100);
  assert.equal((await page.locator('#hourlyAxis').boundingBox()).x,axisX,'mobile axis must remain fixed during horizontal scroll');
  await verifyAxis();
  await page.locator('.hour-button[data-known="true"]').first().click();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await verifyBreakdown(hour);
  assert.ok(await page.locator('#domainPanel').isHidden());
  assert.ok(await page.locator('#restoreDayButton').isVisible());
  if(process.env.VTD_SCREENSHOT)await page.screenshot({path:process.env.VTD_SCREENSHOT.replace('.png','-mobile.png'),fullPage:true});
  await page.click('#restoreDayButton');
  assert.equal((await amounts()).reduce((s,r)=>s+r[2],0),dayActual);
  await page.locator(`.hour-button[data-hour="${hour}"]`).click();await page.click('#monthTab');await settled();
  assert.equal(await page.locator('#categoryScope').getAttribute('data-scope'),'month');assert.ok(await page.locator('#restoreDayButton').isHidden());
  assert.equal((await amounts()).reduce((sum,row)=>sum+row[2],0),monthActual);
  await page.click('#dayTab');await settled();assert.equal((await amounts()).reduce((sum,row)=>sum+row[2],0),dayActual);
  const legacy=await context.newPage();
  await legacy.route('**/data/*.json',async route=>{if(route.request().url().includes('domains-'))return route.continue();const response=await route.fetch();const data=await response.json();delete data.hourly;delete data.hourly_started_at;await route.fulfill({response,json:data});});
  await legacy.goto(url);await legacy.waitForFunction(()=>!document.getElementById('statistics').hasAttribute('aria-busy'));
  assert.ok(await legacy.locator('#hourlyEmpty').isVisible());assert.ok((await legacy.locator('#hourlyCoverage').textContent()).includes('尚未启用'));await legacy.close();
  // Verify zero, byte-sized and large hourly totals using isolated synthetic responses.
  for(const [peak,unit] of [[0,'B'],[1,'B'],[18*1024**2,'MiB'],[5*1024**3,'GiB']]){
   const fixture=await context.newPage();let dropHours=false;
   await fixture.route('**/data/*.json',async route=>{
    if(route.request().url().includes('domains-'))return route.continue();
    const response=await route.fetch(),data=await response.json();
    if(data.hourly)data.hourly[monthId]=dropHours?{}:{'12':{other:{upload:0,download:peak}}};
    await route.fulfill({response,json:data});
   });
   await fixture.goto(url);await fixture.waitForFunction(()=>!document.getElementById('statistics').hasAttribute('aria-busy'));
   await fixture.locator('.hour-button[data-hour="12"]').click();
   const rowTotal=await fixture.locator('#categoryRows tr').evaluateAll(rows=>rows.reduce((sum,row)=>sum+Number(row.cells[3].title.replace(/[^0-9]/g,'')),0));assert.equal(rowTotal,peak);
   const shares=await fixture.locator('.category-share').allTextContents();assert.ok(shares.every(t=>!t.includes('NaN')));
   const geometry=await verifyAxis(fixture);assert.equal(geometry.unit,`流量（${unit}）`);
   assert.equal(geometry.bars.length,1);assert.equal(geometry.bars[0].total,peak);
   assert.equal(await fixture.locator('.hour-button:disabled').count(),23,'missing hours must remain unknown');
   if(peak===18*1024**2)assert.deepEqual(geometry.ticks.map(t=>t.bytes/1024**2),[0,5,10,15,20]);
   if(peak===0){dropHours=true;await fixture.click('#refreshButton');await fixture.waitForFunction(()=>!document.getElementById('statistics').hasAttribute('aria-busy'));assert.ok(await fixture.locator('#hourlyEmpty').isVisible());assert.ok(await fixture.locator('#restoreDayButton').isHidden());assert.equal(await fixture.locator('#categoryScope').getAttribute('data-scope'),'day');}
   await fixture.close();
  }
  console.log(JSON.stringify({hourlyBreakdown:true,restoreDaily:true,exactCategoryShares:true,hourlyCSV:true,refreshKeepsHour:true,domainScopeProtection:true,hourlyAxis:true,scaleGeometry:true,zeroAndLargeValues:true,fixedMobileAxis:true,hourlyExactTotals:true,hourClick:true,categoryAutoFilter:true,historicalDay:true,legacyCoverage:true,dayBytes:dayActual,monthBytes:monthActual,categories:index.categories.length,csvRows:lines.length,emptyPeriod:true,trendNavigation:true,desktop:true,mobile:true,errors}));
  assert.deepEqual(errors,[]);
  await context.close();
 }finally{
  if(browser)await browser.close();
  if(server.exitCode===null){server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));}
  await fs.rm(temp,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
