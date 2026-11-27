"use strict";
const assert=require("node:assert/strict");
const {validate}=require("../cloud/frontend/provider_settings.js");
const good={configuration:{revision:"9007199254740993",provider:"deepseek",model:"synthetic",enabled:true},choices:[{provider:"deepseek",model:"synthetic"}]};
assert.equal(validate(good).configuration.revision,"9007199254740993");
for(const bad of [{...good,configuration:{...good.configuration,revision:1}},{...good,configuration:{...good.configuration,revision:"01"}},{...good,choices:[{provider:"deepseek",model:"https://bad"}]},{...good,choices:[...good.choices,...good.choices]}])assert.throws(()=>validate(bad));
assert.equal(validate({...good,configuration:{...good.configuration,secret:"fictional"}}).configuration.secret,undefined);
console.log("Provider settings response validation passed");
