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
  await page.click('#monthTab');await settled();
  const monthActual=(await amounts()).reduce((s,r)=>s+r[2],0);
  assert.equal(monthActual,index.month_totals[monthId.slice(0,7)].upload+index.month_totals[monthId.slice(0,7)].download);
  const downloading=page.waitForEvent('download');await page.click('#exportButton');
  const download=await downloading;const csvPath=path.join(temp,'export.csv');await download.saveAs(csvPath);
  const lines=(await fs.readFile(csvPath,'utf8')).trim().split('\n');assert.equal(lines.length,index.categories.length+1);
  const csvTotal=lines.slice(1).reduce((s,l)=>s+Number(l.trim().split(',').at(-1).replaceAll('"','')),0);assert.equal(csvTotal,monthActual);
  await page.locator('#periodInput').fill('1900-01');await page.locator('#periodInput').dispatchEvent('change');await settled();
  assert.ok(await page.locator('#empty').isVisible());assert.ok(await page.locator('#exportButton').isDisabled());
  await page.click('#todayButton');await settled();await page.locator('.trend-button').first().click();await settled();
  assert.equal(await page.locator('#dayTab').getAttribute('aria-selected'),'true');
  await page.click('#todayButton');await settled();await page.click('#refreshButton');await settled();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  if(process.env.VTD_SCREENSHOT)await page.screenshot({path:process.env.VTD_SCREENSHOT,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.ok(await page.locator('#exportButton').isVisible());assert.deepEqual(errors,[]);
  console.log(JSON.stringify({dayBytes:dayActual,monthBytes:monthActual,categories:index.categories.length,csvRows:lines.length,emptyPeriod:true,trendNavigation:true,desktop:true,mobile:true,errors}));
  await context.close();
 }finally{
  if(browser)await browser.close();
  if(server.exitCode===null){server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));}
  await fs.rm(temp,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
