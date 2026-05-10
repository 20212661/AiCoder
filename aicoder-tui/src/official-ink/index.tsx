import React from "react";
import { render } from "ink";
import { App } from "./App.js";

const { waitUntilExit } = render(React.createElement(App));

export { waitUntilExit };