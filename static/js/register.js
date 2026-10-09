// Show only the fields belonging to the selected account type.
// An element opts in with data-role="company" or data-role="company university"
// for fields shared by more than one type.
(function () {
  var form = document.getElementById("signup");
  if (!form) return;

  var scoped = form.querySelectorAll("[data-role]");

  function sync() {
    var picked = form.querySelector('input[name="role"]:checked');
    var role = picked ? picked.value : "company";

    scoped.forEach(function (el) {
      var mine = el.dataset.role.split(/\s+/).indexOf(role) !== -1;
      el.hidden = !mine;
      el.querySelectorAll("input, select, textarea").forEach(function (input) {
        input.disabled = !mine;
      });
      if (el.matches("input, select, textarea")) el.disabled = !mine;
    });
  }

  form.querySelectorAll('input[name="role"]').forEach(function (radio) {
    radio.addEventListener("change", sync);
  });
  sync();
})();
