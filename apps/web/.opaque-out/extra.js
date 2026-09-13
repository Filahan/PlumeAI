const path=require('path');const Module=require('module');const orig=Module._resolveFilename;
Module._resolveFilename=function(r,...a){if(r.startsWith('@/'))r=path.join(__dirname,'src',r.slice(2));return orig.call(this,r,...a);};
const { isOpaqueIdentifier, identifierStem } = require('./src/components/automations/inspector/schema-form/opaque-field.js');
const cases = [
  ['channelId', {type:'string'}], ['pageIDs', {type:'string'}], ['guild_ids', {type:'string'}],
  ['id', {type:'integer'}], ['ts', {type:'string'}], ['messageTs', {type:'string'}],
  ['valid', {type:'string'}], ['uuid', {type:'string'}], ['grid', {type:'string'}],
  ['hybrid', {type:'string'}], ['void', {type:'string'}], ['candid', {type:'string'}],
  ['channel', {type:'string'}], ['title', {type:'string'}],
  ['target', {type:'string', description:'The Notion page ID to update.'}],
  ['target', {type:'string', description:'A unique identifier for the record.'}],
  ['user', {type:'string', description:'Discord snowflake of the user.'}],
  ['note', {type:'string', description:'Consider the arachnid id of the thing'}],
  ['kind', {type:'string', enum:['a','b'], description:'The ID of the kind'}],
  ['channel_id', {type:'array'}], ['channel_id', {}], ['channel_id', {type:['string','null']}],
  ['record_id', {type:'string', enum:['x']}],
];
for (const [n,s] of cases) console.log((isOpaqueIdentifier(n,s)?'FLAG  ':'plain '), n, JSON.stringify(s), '| stem=', JSON.stringify(identifierStem(n)));
