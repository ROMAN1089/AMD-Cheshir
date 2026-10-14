// Stream uploads to Flask; never buffer the video in a route handler.
export const runtime='nodejs';
export async function POST(request:Request){
 const headers=new Headers();
 for(const name of ['content-type','cookie','origin']){const v=request.headers.get(name);if(v)headers.set(name,v);}
 try{
  const result=await fetch(`${process.env.BACKEND_URL||'http://127.0.0.1:5000'}/api/process_video`,{method:'POST',headers,body:request.body,duplex:'half',signal:AbortSignal.timeout(300000)} as RequestInit&{duplex:string});
  return new Response(result.body,{status:result.status,headers:{'content-type':result.headers.get('content-type')||'application/json','cache-control':'no-store'}});
 }catch{return Response.json({error:'The upload could not reach the video service. Check the connection and try again.'},{status:502});}
}
