const base = require("./playwright.config.js");
delete base.use.launchOptions;
module.exports = base;
