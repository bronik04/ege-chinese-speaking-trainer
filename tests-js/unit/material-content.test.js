import assert from "node:assert/strict";
import test from "node:test";

import { editableMaterialContent } from "../../frontend/js/materials/material-content.js";

test("published task content is projected onto editable draft fields", () => {
  const source = {
    "2": {
      prepSeconds: 120,
      answerSeconds: 120,
      title: "Fixed title",
      lead: "Fixed lead",
      prompts: ["fixed"],
      starter: "fixed",
      images: ["one", "two", "three"],
      unknown: true,
    },
  };

  assert.deepEqual(editableMaterialContent("task", 2, source), {
    "2": { images: ["one", "two", "three"] },
  });
  assert.equal(source["2"].unknown, true);
});

test("full draft gets every exact field and repairs invalid legacy value types", () => {
  const result = editableMaterialContent("full", null, {
    "1": { situation: 4, questions: ["one"], image: "asset" },
    "3": { title: "Project", images: null, imageLabels: ["First", 2] },
  });

  assert.deepEqual(result, {
    "1": {
      situation: "",
      banner: "",
      questions: ["one", "", "", "", ""],
      image: "asset",
      imageAlt: "",
    },
    "2": { images: ["", "", ""] },
    "3": {
      title: "Project",
      images: ["", ""],
      imageLabels: ["First", ""],
    },
  });
});
