import {defineConfig} from '@playwright/test';
export default defineConfig({
 testDir:'./tests/browser',workers:1,fullyParallel:false,timeout:45000,
 reporter:'list',use:{baseURL:'http://127.0.0.1:3000',trace:'retain-on-failure'},
 webServer:[
  {command:'python ../snapsell-backend/tests/browser_server.py',url:'http://127.0.0.1:5000/api/health',reuseExistingServer:false},
  {command:'node node_modules/next/dist/bin/next start --hostname 127.0.0.1',url:'http://127.0.0.1:3000',reuseExistingServer:false,timeout:120000}
 ]
});
