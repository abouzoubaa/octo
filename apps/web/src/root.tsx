import { component$ } from "@builder.io/qwik";
import { QwikCityProvider, RouterOutlet, ServiceWorkerRegister } from "@builder.io/qwik-city";

import "./global.css";

// Applied before first paint: ?theme= override → saved choice → system preference.
const THEME_BOOTSTRAP = `(function(){try{
var m=/[?&]theme=(dark|light)/.exec(location.search);
var s=null;try{s=localStorage.getItem('theme')}catch(e){}
var d=m?m[1]==='dark':(s?s==='dark':!!(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches));
if(d)document.documentElement.className+=' dark';
}catch(e){}})()`;

export default component$(() => {
  return (
    <QwikCityProvider>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <meta name="color-scheme" content="light dark" />
        <title>Search the archive</title>
        <script dangerouslySetInnerHTML={THEME_BOOTSTRAP} />
      </head>
      <body lang="en">
        <RouterOutlet />
        <ServiceWorkerRegister />
      </body>
    </QwikCityProvider>
  );
});
