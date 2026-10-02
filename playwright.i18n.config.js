const base = require('./playwright.config');
module.exports = {...base, webServer:undefined, testMatch:['i18n.spec.js','i18n-screens.spec.js'],
  use:{...base.use, baseURL:process.env.RMS_I18N_BASE_URL || 'http://127.0.0.1:4180'},
};
