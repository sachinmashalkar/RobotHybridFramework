*** Settings ***
Documentation       Central imports so suites only need one resource import.
...
...                 Any suite that imports this file gets access to SeleniumLibrary,
...                 custom Python libraries, page objects, and shared keywords.

Library             Collections
Library             DateTime
Library             OperatingSystem
Library             Process
Library             String
Library             SeleniumLibrary    timeout=20s    implicit_wait=2s
...                     plugins=libraries.SelfHealingPlugin.SelfHealingPlugin
Library             RequestsLibrary
Library             JSONLibrary
Library             DatabaseLibrary
Library             libraries.ConfigManager    AS    Config
Library             libraries.BrowserFactory    AS    Browser
Library             libraries.CdpConnector    AS    CdpConnect
Library             libraries.DataProvider    AS    Data
Library             libraries.APIClient    AS    API
Library             libraries.Utils    AS    Utils
Resource            ../common/common_keywords.resource
Resource            ../pages/base_page.resource
Resource            ../pages/login_page.resource
Resource            ../pages/home_page.resource
