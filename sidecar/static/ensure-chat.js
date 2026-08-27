// ponytail: Grist has no page-template hook (official move is Duplicate page).
// Same-origin poll on the Grist shell adds Chat after Add Page. Drop if Grist ships templates.
(function () {
  var CHAT = "/chat";
  var busy = false;

  function planEnsureChat(pages, views, sections) {
    var pageViews = {};
    pages.forEach(function (p) {
      pageViews[p.fields.viewRef] = true;
    });
    var byView = {};
    sections.forEach(function (s) {
      var vid = s.fields.parentId;
      if (!vid) return;
      (byView[vid] || (byView[vid] = [])).push(s);
    });
    var viewById = {};
    views.forEach(function (v) {
      viewById[v.id] = v;
    });
    var need = [];
    Object.keys(pageViews).forEach(function (vid) {
      vid = Number(vid);
      var ss = byView[vid] || [];
      var table = ss.filter(function (s) {
        return s.fields.parentKey === "record";
      })[0];
      var chat = ss.filter(function (s) {
        return s.fields.parentKey === "custom" && String(s.fields.options || "").indexOf(CHAT) !== -1;
      })[0];
      if (table && !chat) {
        need.push({
          viewId: vid,
          tableRef: table.fields.tableRef,
          tableSectionId: table.id,
          layoutSpec: (viewById[vid] && viewById[vid].fields.layoutSpec) || "",
        });
      }
    });
    return need;
  }

  function withChatLayout(layoutSpec, tableLeaf, chatLeaf) {
    var layout = {};
    if (layoutSpec) {
      try {
        layout = typeof layoutSpec === "string" ? JSON.parse(layoutSpec) : layoutSpec;
      } catch (e) {
        layout = {};
      }
    }
    var dump = JSON.stringify(layout);
    if (dump.indexOf('"leaf":' + chatLeaf) !== -1 || dump.indexOf('"leaf": ' + chatLeaf) !== -1) {
      return JSON.stringify(layout);
    }
    var item = { size: 120, leaf: chatLeaf };
    if (!layout.children || !layout.children.length) {
      layout = { children: [{ children: [{ size: 80, leaf: tableLeaf }, item] }], collapsed: [] };
    } else {
      var row = layout.children[0];
      if (row && Array.isArray(row.children)) row.children.push(item);
      else layout.children.push({ children: [{ size: 80, leaf: tableLeaf }, item] });
      if (!layout.collapsed) layout.collapsed = [];
    }
    return JSON.stringify(layout);
  }

  function docId() {
    var m = location.pathname.match(/\/o\/docs\/([^/]+)/);
    return m && m[1];
  }

  function recs(id, table) {
    return fetch("/api/docs/" + id + "/tables/" + table + "/records", { credentials: "same-origin" }).then(function (r) {
      return r.json();
    }).then(function (j) {
      return j.records || [];
    });
  }

  function apply(id, actions) {
    return fetch("/api/docs/" + id + "/apply", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(actions),
    }).then(function (r) {
      return r.json();
    });
  }

  function chatOptions() {
    return JSON.stringify({
      customView: JSON.stringify({
        mode: "url",
        url: location.origin + CHAT,
        access: "full",
        renderAfterReady: true,
      }),
    });
  }

  function tick() {
    var id = docId();
    if (!id || busy) return;
    busy = true;
    Promise.all([recs(id, "_grist_Pages"), recs(id, "_grist_Views"), recs(id, "_grist_Views_section")])
      .then(function (xs) {
        var need = planEnsureChat(xs[0], xs[1], xs[2]);
        function next(i) {
          if (i >= need.length) {
            busy = false;
            return;
          }
          var n = need[i];
          apply(id, [["CreateViewSection", n.tableRef, n.viewId, "custom", null, null]]).then(function (out) {
            var sectionRef = out.retValues && out.retValues[0] && out.retValues[0].sectionRef;
            if (!sectionRef) {
              busy = false;
              return;
            }
            return apply(id, [
              [
                "UpdateRecord",
                "_grist_Views_section",
                sectionRef,
                { title: "Chat", options: chatOptions(), linkSrcSectionRef: n.tableSectionId },
              ],
              ["UpdateRecord", "_grist_Views", n.viewId, { layoutSpec: withChatLayout(n.layoutSpec, n.tableSectionId, sectionRef) }],
            ]).then(function () {
              next(i + 1);
            });
          }).catch(function () {
            busy = false;
          });
        }
        next(0);
      })
      .catch(function () {
        busy = false;
      });
  }

  if (typeof window === "undefined") {
    var need = planEnsureChat(
      [
        { id: 1, fields: { viewRef: 1 } },
        { id: 2, fields: { viewRef: 2 } },
      ],
      [
        { id: 1, fields: { layoutSpec: "" } },
        { id: 2, fields: { layoutSpec: "" } },
      ],
      [
        { id: 1, fields: { parentId: 1, parentKey: "record", tableRef: 1, options: "" } },
        { id: 4, fields: { parentId: 1, parentKey: "custom", tableRef: 1, options: '{"url":"/chat"}' } },
        { id: 5, fields: { parentId: 2, parentKey: "record", tableRef: 2, options: "" } },
      ],
    );
    if (need.length !== 1 || need[0].viewId !== 2) throw new Error(JSON.stringify(need));
  } else if (/\/o\/docs\//.test(location.pathname) && !window.__sihEnsureChat) {
    window.__sihEnsureChat = true;
    tick();
    setInterval(tick, 2500);
  }
})();
