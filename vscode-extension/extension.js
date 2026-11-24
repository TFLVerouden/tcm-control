const vscode = require("vscode");
const path = require("path");

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("tcmConfigRunner.run", async () => {
      const document = vscode.window.activeTextEditor?.document;
      if (!document || document.uri.scheme !== "file" ||
          path.extname(document.fileName).toLowerCase() !== ".toml") {
        vscode.window.showErrorMessage("Open an experiment TOML file before running.");
        return;
      }

      const folder = vscode.workspace.getWorkspaceFolder(document.uri);
      if (!folder || folder.uri.scheme !== "file") {
        vscode.window.showErrorMessage("Open the control repository as a workspace first.");
        return;
      }

      const runner = vscode.Uri.joinPath(folder.uri, "run.py");
      try {
        await vscode.workspace.fs.stat(runner);
      } catch (error) {
        vscode.window.showErrorMessage(`Cannot access ${runner.fsPath}: ${error.message}`);
        return;
      }

      if (document.isDirty && !(await document.save())) {
        vscode.window.showErrorMessage("The experiment TOML could not be saved.");
        return;
      }

      try {
        const extension = vscode.extensions.getExtension("ms-python.python");
        if (!extension) {
          throw new Error("Install the Microsoft Python extension and select an interpreter.");
        }
        const api = await extension.activate();
        await api.ready;
        const selected = api.environments.getActiveEnvironmentPath(folder.uri);
        const environment = await api.environments.resolveEnvironment(selected);
        const interpreter = environment?.executable.uri?.fsPath;
        if (!interpreter) {
          throw new Error("Select a valid Python interpreter for this workspace.");
        }

        const task = new vscode.Task(
          { type: "tcm-config-runner" },
          folder,
          "Run TCM experiment",
          "TCM",
          new vscode.ProcessExecution(interpreter, [runner.fsPath, document.uri.fsPath], {
            cwd: folder.uri.fsPath
          })
        );
        task.presentationOptions = { reveal: vscode.TaskRevealKind.Always, focus: true };
        await vscode.tasks.executeTask(task);
      } catch (error) {
        vscode.window.showErrorMessage(`Could not start the experiment: ${error.message}`);
      }
    })
  );
}

module.exports = { activate };
