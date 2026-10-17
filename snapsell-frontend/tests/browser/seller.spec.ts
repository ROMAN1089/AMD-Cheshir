import {test,expect} from '@playwright/test';

test('manual photo, concurrent price, reload and marketplace kit',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Open seller workspace',exact:true}).click();
 await page.getByRole('button',{name:'Inventory',exact:true}).click();
 await page.getByRole('button',{name:'Add manually',exact:true}).click();
 await page.getByRole('textbox',{name:'Listing title',exact:true}).fill('Blue ceramic mug');
 await page.getByRole('spinbutton',{name:'Asking price ($)',exact:true}).fill('60');
 await page.getByRole('button',{name:'Save draft',exact:true}).click();
 await page.getByRole('button',{name:/^Blue ceramic mug/}).click();
 const dialog=page.getByRole('dialog',{name:'Listing workspace'});
 // Disposable generated pixel fixture, never written to the actual seller inventory.
 await dialog.locator('input[type=file]').setInputFiles({name:'mug.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=','base64')});
 await expect(dialog.getByRole('img',{name:'Product photo 1',exact:true})).toBeVisible();
 const workspace=await (await page.request.get('/api/workspace')).json();
 const item=workspace.items.find((row:any)=>row.title==='Blue ceramic mug');
 // Simulate research completing while the editor still displays its earlier price.
 expect((await page.request.patch(`/api/items/${item.id}`,{data:{price:80}})).ok()).toBeTruthy();
 await dialog.getByRole('textbox',{name:'Description',exact:true}).fill('Checked by the seller.');
 await dialog.getByRole('button',{name:'Save changes',exact:true}).click();
 await expect(dialog.getByRole('spinbutton',{name:'Asking price ($)',exact:true})).toHaveValue('80');
 await dialog.getByRole('checkbox',{name:'I verified the description, condition, and specifications.'}).check();
 await dialog.getByRole('button',{name:'Confirm product facts',exact:true}).click();
 await expect(dialog).not.toBeVisible();
 await page.reload();await page.getByRole('button',{name:'Inventory',exact:true}).click();
 await expect(page.getByRole('button',{name:/^Blue ceramic mug/})).toContainText('$80');
 const kit=await (await page.request.get(`/api/items/${item.id}/channels/facebook`)).json();
 expect(kit.price_usd).toBe(80);expect(kit.photo_available).toBeTruthy();expect(kit.publication_status).toBe('not_published');
});

test('mobile dialog covers navigation and protects edits on Escape',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto('/');
 await page.getByRole('button',{name:'Open seller workspace',exact:true}).click();
 await page.getByRole('button',{name:'Inventory',exact:true}).click();
 await page.getByRole('button',{name:'Add manually',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Add a new item'});
 await dialog.getByRole('textbox',{name:'Listing title',exact:true}).fill('Unsaved item');
 await dialog.getByRole('textbox',{name:'Listing title',exact:true}).press('Escape');
 await expect(dialog.getByText('You have unsaved listing changes.',{exact:true})).toBeVisible();
 await dialog.getByRole('button',{name:'Keep editing',exact:true}).click();
 await expect(dialog).toBeVisible();
 const layers=await page.evaluate(()=>({modal:Number(getComputedStyle(document.querySelector('.modal-backdrop')!).zIndex),nav:Number(getComputedStyle(document.querySelector('.sidebar')!).zIndex)}));
 expect(layers.modal).toBeGreaterThan(layers.nav);
});
