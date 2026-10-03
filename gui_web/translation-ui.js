/* Description translation is explicit; accepted text enters the existing editor draft. */
(function () {
  'use strict';
  window.RMSTranslationUI = {create(ctx) {
    const {h,api,showModal,closeModal,showToast,pollJob,openSettings} = ctx;
    const t=(key,params)=>window.RMSI18n.t(key,params);
    function settingsEditor() {
      const box=h('div',{class:'translation-settings'});
      (async()=>{
        const r=await api.translationSettings();
        if(!r.ok){box.appendChild(h('div',{class:'stg-info'},[window.RMSI18n.formatError(r.error)]));return;}
        const mode=h('select',{class:'field-input translation-mode'},[
          ...[['off','ui.translation.mode.off'],['deepl-free','ui.translation.mode.deepl-free'],['deepl-pro','ui.translation.mode.deepl-pro'],['google','ui.translation.mode.google']].map(([value,label])=>h('option',{value},[t(label)]))]);
        mode.value=r.data.mode;
        const key=h('input',{type:'password',class:'field-input translation-key',autocomplete:'new-password',placeholder:t(r.data.hasKey?'ui.translation.keySaved':'ui.translation.key')});
        const status=h('div',{class:'modal-hint translation-settings-result'});
        const save=h('button',{class:'btn compact',onClick:async()=>{
          save.disabled=true;
          try {
            const result=await api.saveTranslationSettings(mode.value,key.value.trim()||null);
            status.textContent=result.ok?t('ui.translation.settingsSaved'):window.RMSI18n.formatError(result.error);
            if(result.ok){key.value='';key.placeholder=t(result.data.hasKey?'ui.translation.keySaved':'ui.translation.key');}
          }finally{save.disabled=false;}
        }},[t('ui.translation.saveSettings')]);
        box.appendChild(h('div',{class:'field-label'},[t('ui.translation.service')]));box.appendChild(mode);
        box.appendChild(h('div',{class:'field-label'},[t('ui.translation.key')]));box.appendChild(key);
        box.appendChild(h('div',{class:'modal-hint'},[t('ui.translation.disclosure')]));
        box.appendChild(h('div',{class:'translation-settings-actions'},[save,status]));
      })();
      return box;
    }
    async function open(input,owner,gameKey,isCurrent,onChange) {
      const source=input.value;
      if(!source.trim())return;
      const configured=await api.translationSettings();
      if(!isCurrent()||!input.isConnected)return;
      if(!configured.ok){showToast(configured.error,'error');return;}
      if(configured.data.mode==='off'||!configured.data.hasKey){showToast(t('ui.translation.configure'),'warning');openSettings('metadata');return;}
      let closed=false,busy=false,jobId=null,result=null;
      const original=h('textarea',{class:'field-input translation-original',rows:6,readonly:true});original.value=source;
      const translated=h('textarea',{class:'field-input translation-result',rows:6,readonly:true});
      const language=h('select',{class:'field-input translation-language'},window.RMSI18n.LANGS.map(value=>h('option',{value},[window.RMSI18n.LABELS[value]])));
      language.value=ctx.language();
      const status=h('div',{class:'modal-hint translation-status'});
      const host=h('div',{class:'translation-progress'});
      const close=()=>{closed=true;if(jobId)api.cancelJob(jobId);closeModal();};
      const apply=h('button',{class:'btn primary translation-apply',disabled:true,onClick:async()=>{
        if(busy||!result)return;
        if(!isCurrent()||!input.isConnected||input.value!==source){status.textContent=t('ui.translation.stale');apply.disabled=true;return;}
        busy=true;apply.disabled=true;start.disabled=true;restore.disabled=true;language.disabled=true;
        const remembered=await api.rememberDescriptionTranslation(gameKey,result);
        if(closed)return;
        if(!remembered.ok){busy=false;apply.disabled=false;start.disabled=false;language.disabled=false;status.textContent=window.RMSI18n.formatError(remembered.error);return;}
        if(!isCurrent()||input.value!==source){busy=false;status.textContent=t('ui.translation.stale');return;}
        input.value=result.translated;onChange();close();showToast(t('ui.translation.draftReady'),'success');
      }},[t('ui.translation.useTranslation')]);
      const restore=h('button',{class:'btn translation-restore',disabled:true,onClick:()=>{
        if(busy||!isCurrent()||input.value!==source)return;
        input.value=original.value;onChange();close();showToast(t('ui.translation.draftReady'),'success');
      }},[t('ui.translation.useOriginal')]);
      const start=h('button',{class:'btn primary compact translation-start',onClick:async()=>{
        if(busy)return;busy=true;result=null;apply.disabled=true;restore.disabled=true;start.disabled=true;language.disabled=true;status.textContent='';translated.value='';
        try{
          const started=await api.startTranslateDescription(source,language.value);
          if(closed){if(started.ok)api.cancelJob(started.data.jobId);return;}
          if(!started.ok){status.textContent=window.RMSI18n.formatError(started.error);return;}
          jobId=started.data.jobId;
          const completed=await pollJob(jobId,t('ui.translation.working'),host);jobId=null;
          if(closed)return;
          if(!completed.ok){status.textContent=window.RMSI18n.formatError(completed.error);return;}
          result=completed.data;translated.value=result.translated;
          status.textContent=t(result.cached?'ui.translation.cached':'ui.translation.ready');apply.disabled=false;
        }finally{if(!closed){busy=false;start.disabled=false;language.disabled=false;restore.disabled=original.value===source;}}
      }},[t('ui.translation.start')]);
      language.addEventListener('change',()=>{result=null;apply.disabled=true;translated.value='';status.textContent='';});
      const body=h('div',{class:'modal-body translation-body'},[
        h('div',{class:'translation-controls'},[h('span',{class:'field-label'},[t('ui.translation.target')]),language,start]),
        host,status,h('div',{class:'translation-grid'},[
          h('div',{},[h('div',{class:'field-label'},[t('ui.translation.original')]),original]),
          h('div',{},[h('div',{class:'field-label'},[t('ui.translation.translated')]),translated])]),
        h('div',{class:'modal-hint'},[t('ui.translation.draftHelp')])]);
      showModal(t('ui.translation.title'),body,[restore,h('button',{class:'btn',onClick:close},[t('ui.translation.cancel')]),apply]);
      const backup=await api.originalDescription(gameKey,source);
      if(!closed&&backup.ok&&backup.data){original.value=backup.data;restore.disabled=false;}
    }
    return {settingsEditor,open};
  }};
})();
