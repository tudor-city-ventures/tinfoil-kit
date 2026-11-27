// The app reads the kit's list from the website's data (../site/kit.json and sources.json), so Metro looks there too.
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);
const site = path.resolve(__dirname, "../site");
config.watchFolders = [site];
config.resolver.blockList = [new RegExp(`${site}/(node_modules|\\.next|out)/.*`)];
module.exports = config;
