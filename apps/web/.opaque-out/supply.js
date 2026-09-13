const path=require('path');const Module=require('module');const orig=Module._resolveFilename;
Module._resolveFilename=function(r,...a){if(r.startsWith('@/'))r=path.join(__dirname,'src',r.slice(2));return orig.call(this,r,...a);};
const fs=require('fs');
const { opaqueFieldState } = require('./src/components/automations/inspector/schema-form/opaque-field.js');
const catalog = JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const action=(id,integration,name)=>({id,name:id,type:'action',valid:true,settings:{integration,action:name,input:{}}});
const aiText=(id)=>({id,name:id,type:'ai',valid:true,settings:{instructions:'x',tools:[],output:{mode:'text'}}});
const aiJson=(id,props)=>({id,name:id,type:'ai',valid:true,settings:{instructions:'x',tools:[],output:{mode:'json',schema:{type:'object',properties:props}}}});
const filter=(id)=>({id,name:id,type:'filter',valid:true,settings:{mode:'rules',rules:{combinator:'and',conditions:[]}}});
const target=action('step_target','discord','discord_send_message');
const run=(rows)=>({steps:rows});
const scenarios=[
 ['no earlier step', [target], null],
 ['after slack_list_channels (declares channels[])', [action('step_a','slack','slack_list_channels'), target], null],
 ['after discord_list_channels (no schema, never run)', [action('step_a','discord','discord_list_channels'), target], null],
 ['after gmail_send (no schema, never run)', [action('step_a','gmail','gmail_send'), target], null],
 ['after AI text step', [aiText('step_a'), target], null],
 ['after AI json step {summary}', [aiJson('step_a',{summary:{type:'string'}}), target], null],
 ['after AI json step {channel_id}', [aiJson('step_a',{channel_id:{type:'string'}}), target], null],
 ['after filter step', [filter('step_a'), target], null],
 ['after notion_get_page (declares id)', [action('step_a','notion','notion_get_page'), target], null],
 ['after notion_append_blocks (declares appended only)', [action('step_a','notion','notion_append_blocks'), target], null],
 ['after a step whose LAST RUN returned channels[0].id', [action('step_a','discord','discord_list_channels'), target],
   run([{stepId:'step_a',output:{channels:[{id:'1',name:'general'}]}}])],
 ['after a step whose LAST RUN returned {ok:true}', [action('step_a','discord','discord_list_channels'), target],
   run([{stepId:'step_a',output:{ok:true}}])],
];
for (const [label, steps, r] of scenarios) {
  const st = opaqueFieldState('channel_id', {type:'string', description:'Channel id.'}, steps, 'step_target', catalog, r);
  console.log((st.block? 'BLOCKED ':'allowed '), label);
}
console.log('--- non-opaque control (content) ---');
console.log(JSON.stringify(opaqueFieldState('content', {type:'string'}, [target], 'step_target', catalog, null)));
console.log('--- thread_ts, no earlier steps / after slack_read_messages ---');
console.log(JSON.stringify(opaqueFieldState('thread_ts', {type:'string'}, [target], 'step_target', catalog, null)));
console.log(JSON.stringify(opaqueFieldState('thread_ts', {type:'string'}, [action('step_a','slack','slack_read_messages'), target], 'step_target', catalog, null)));
