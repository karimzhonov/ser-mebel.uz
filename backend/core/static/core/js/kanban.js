/* Dashboard kanban: switch between boards, unfold a collapsed terminal column.
   Everything is rendered server-side (core/templates/index.html); this only
   toggles visibility. Boards are read-only — there is no drag-and-drop, because a
   status change has to go through the admin actions that send the SMS and keep the
   order of statuses. */
(function () {
    "use strict";

    function init() {
        var root = document.querySelector("[data-kanban]");
        if (!root) return;

        var tabs = Array.prototype.slice.call(root.querySelectorAll("[data-kanban-tab]"));

        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                select(tab.getAttribute("data-kanban-tab"));
            });
        });

        function select(id) {
            tabs.forEach(function (tab) {
                var on = tab.getAttribute("data-kanban-tab") === id;
                tab.setAttribute("aria-selected", on ? "true" : "false");
                var board = document.getElementById("kanban-board-" + tab.getAttribute("data-kanban-tab"));
                if (board) board.hidden = !on;
            });
            try {
                localStorage.setItem("kanban-tab", id);
            } catch (e) {
                /* private window or blocked storage — remembering the tab is optional */
            }
        }

        var remembered = null;
        try {
            remembered = localStorage.getItem("kanban-tab");
        } catch (e) {
            remembered = null;
        }
        if (remembered && document.getElementById("kanban-board-" + remembered)) {
            select(remembered);
        }

        /* Terminal columns fold and unfold; the header is the handle, so clicking a
           card inside an open column still follows its link. */
        root.querySelectorAll("[data-kanban-collapsible]").forEach(function (col) {
            var head = col.querySelector(".kanban-col-head");
            if (!head) return;
            head.addEventListener("click", function (event) {
                event.preventDefault();
                col.classList.toggle("is-collapsed");
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
